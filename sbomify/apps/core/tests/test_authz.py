"""Characterization tests for the ``can()`` authorization front door.

These pin the role->capability behaviour and prove ``can`` is a faithful
delegation: its decision equals the existing ``verify_item_access`` /
``check_component_access`` for every role, resource and action — so migrating a
call site onto ``can`` cannot change behaviour.
"""

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpRequest

from sbomify.apps.core import authz
from sbomify.apps.core.authz import Decision, UnknownActionError, can
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.teams.models import Member, Team


def _user(username: str):
    return get_user_model().objects.create_user(username=username[:150], password="x")


def _member(team, user, role):
    """Create a Member, honouring the bot-role guard.

    ``role="bot"`` is reserved for OIDC synthetic identities; a pre_save signal
    rejects manual creation unless the sanctioned provisioning flag is set.
    """
    member = Member(team=team, user=user, role=role)
    if role == "bot":
        member._is_oidc_bot_provisioning = True
    member.save()
    return member


@pytest.fixture
def workspace(db):
    team = Team.objects.create(name="authz-team")
    component = Component.objects.create(name="authz-comp", team=team)
    return team, component


def _resource_for(res_key, team, component):
    """Resolve a matrix resource key to a model the action applies to."""
    if res_key == "team":
        return team
    if res_key == "product":
        return Product.objects.create(name="authz-prod", team=team)
    return component


# (action, resource, expected-allowed per role) — the role->capability matrix.
# This is the authoritative statement of who can do what; a tier change that
# isn't reflected here is a bug in one of the two.
_MATRIX = {
    # Admins are near-owners: workspace governance, member management, billing
    # and deletion of domain resources are all theirs.
    "workspace:administer": ("team", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "billing:manage": ("team", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "member:manage": ("team", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "component:manage": ("component", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "component:delete": ("component", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "product:delete": ("product", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "release:delete": ("product", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "sbom:delete": ("component", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "document:delete": ("component", {"owner": True, "admin": True, "guest": False, "bot": False}),
    # ...except the two OWNER_ONLY carve-outs. Deleting the workspace is the only
    # capability an admin lacks; "an admin may not remove an owner" is relational
    # and lives in the member-removal guards, not here.
    "workspace:delete": ("team", {"owner": True, "admin": False, "guest": False, "bot": False}),
    # #468: guests may upload artifacts (joined the PUBLISH tier).
    "artifact:publish": ("component", {"owner": True, "admin": True, "guest": True, "bot": True}),
    "workspace:read": ("team", {"owner": True, "admin": True, "guest": True, "bot": False}),
    "component:administer": ("component", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "product:read": ("product", {"owner": True, "admin": True, "guest": True, "bot": False}),
    # CI/OIDC publish workflow: a release-cutting bot reads (to check existence),
    # creates, and tags releases — but cannot rename or delete them. Guests stay
    # out of create/tag (they may upload artifacts, not cut releases).
    "release:read": ("product", {"owner": True, "admin": True, "guest": True, "bot": True}),
    "release:create": ("product", {"owner": True, "admin": True, "guest": False, "bot": True}),
    "release:tag": ("product", {"owner": True, "admin": True, "guest": False, "bot": True}),
    "release:manage": ("product", {"owner": True, "admin": True, "guest": False, "bot": False}),
}
_CASES = [(a, role, exp[role]) for a, (_res, exp) in _MATRIX.items() for role in ("owner", "admin", "guest", "bot")]


@pytest.mark.django_db
@pytest.mark.parametrize("action,role,expected", _CASES)
def test_role_capability_matrix(workspace, action, role, expected):
    team, component = workspace
    resource = _resource_for(_MATRIX[action][0], team, component)
    user = _user(f"{role}-{action.replace(':', '-')}")
    _member(team, user, role)

    decision = can(user, action, resource)
    assert isinstance(decision, Decision)
    assert decision.allowed is expected
    assert bool(decision) is expected
    # ...and (not decision) mirrors the legacy `if not verify_item_access(...)`.
    assert (not decision) is (not expected)


# The human role ladder, least- to most-privileged. ``bot`` is deliberately
# absent: it is a synthetic OIDC publishing identity that sits outside the
# ladder (it can publish releases but cannot read most internal data), so
# including it would make the invariant below meaningless.
_ROLE_LADDER = (authz.ROLE_GUEST, authz.ROLE_ADMIN, authz.ROLE_OWNER)


@pytest.mark.parametrize("action", sorted(authz._ROLE_ACTIONS))
def test_role_ladder_is_upward_closed(action):
    """No role may hold a capability that a more-privileged role lacks.

    Every battle-tested permission model (GitLab, Sentry, GitHub) is a ladder
    where each role is a superset of the one below. Keeping that invariant is
    what stops the model degenerating into per-role permission soup, where
    answering "can an admin do X" requires reading every call site. A carve-out
    that breaks inheritance fails here rather than in production.
    """
    granted = authz._ROLE_ACTIONS[action]
    holders = [role in granted for role in _ROLE_LADDER]
    # Once a role on the ladder is granted the action, every role above it must
    # be too — i.e. the boolean sequence is non-decreasing.
    assert holders == sorted(holders), (
        f"{action!r} breaks role inheritance: granted to {sorted(set(granted) & set(_ROLE_LADDER))} "
        f"but not to every more-privileged role (ladder: {' < '.join(_ROLE_LADDER)})"
    )


def test_role_descriptions_cover_every_human_role():
    """The members page explains roles from ROLE_DESCRIPTIONS; a role missing
    there is invisible to users even though it is assignable."""
    described = {role for role, _label, _desc in authz.ROLE_DESCRIPTIONS}
    human_roles = {authz.ROLE_OWNER, authz.ROLE_ADMIN, authz.ROLE_GUEST}
    assert described == human_roles
    assert authz.ROLE_BOT not in described  # synthetic identity, never shown
    for _role, label, description in authz.ROLE_DESCRIPTIONS:
        assert label and description.strip().endswith(".")


@pytest.mark.django_db
@pytest.mark.parametrize("action", list(_MATRIX))
def test_non_member_is_always_denied(workspace, action):
    team, component = workspace
    resource = _resource_for(_MATRIX[action][0], team, component)
    assert can(_user(f"outsider-{action.replace(':', '-')}"), action, resource).allowed is False


@pytest.mark.django_db
def test_can_decision_equals_verify_item_access(workspace):
    """The faithfulness guarantee: can() == verify_item_access for every role."""
    team, component = workspace
    for role in ("owner", "admin", "guest", "bot"):
        user = _user(f"equiv-{role}")
        _member(team, user, role)
        req = HttpRequest()
        req.user = user
        req.session = {}
        assert can(user, "component:manage", component).allowed == verify_item_access(
            req, component, list(authz.MANAGE)
        )
        assert can(user, "artifact:publish", component).allowed == verify_item_access(
            req, component, list(authz.PUBLISH)
        )


@pytest.mark.django_db
def test_request_actor_preserves_token_workspace_scope(workspace):
    """A request actor keeps verify_item_access's token scoping: a token scoped
    to another workspace denies even an owner."""
    team, component = workspace
    owner = _user("scoped-owner")
    _member(team, owner, "owner")
    other_team = Team.objects.create(name="other-ws")

    req = HttpRequest()
    req.user = owner
    req.session = {}
    req.token_team = other_team  # scoped elsewhere
    assert can(req, "component:manage", component).allowed is False

    req.token_team = team  # in scope
    assert can(req, "component:manage", component).allowed is True


@pytest.mark.django_db
def test_abac_action_delegates_to_component_access(workspace):
    team, component = workspace
    outsider = _user("abac-outsider")

    component.visibility = Component.Visibility.PUBLIC
    component.save()
    assert can(outsider, "component:access", component).allowed is True

    component.visibility = Component.Visibility.PRIVATE
    component.save()
    assert can(outsider, "component:access", component).allowed is False

    member = _user("abac-member")
    _member(team, member, "owner")
    assert can(member, "component:access", component).allowed is True


def test_unknown_action_raises():
    with pytest.raises(UnknownActionError):
        can(HttpRequest(), "component:teleport", object())


def test_decision_is_fail_closed_in_boolean_context():
    """Security invariant: a denied Decision MUST be falsy.

    Call sites guard with ``if not can(...)``; that only denies if ``Decision``
    is falsy when ``allowed`` is False. Without ``__bool__`` the object would be
    truthy, ``not can(...)`` would always be False, and every gate would fail
    OPEN. This pins the fail-closed behaviour directly.
    """
    assert bool(Decision(allowed=False)) is False
    assert bool(Decision(allowed=True)) is True
    # `if not can(...)` -> enters the deny branch only for a denied decision.
    assert (not Decision(allowed=False)) is True
    assert (not Decision(allowed=True)) is False


def test_all_can_actions_used_in_code_are_registered():
    """Every action string passed to can() across the (non-test) codebase must
    be registered in the catalog — otherwise can() raises UnknownActionError at
    runtime. Guards against typos / renames that the type checker can't catch.
    """
    import ast
    import pathlib

    apps_root = pathlib.Path(__file__).resolve().parents[2]  # sbomify/apps
    registered = set(authz._ROLE_ACTIONS) | set(authz._ABAC_ACTIONS)

    # Parse the AST and pull the literal 2nd argument of real can(...) calls.
    # This avoids the regex pitfalls of matching quotes/docstrings: it sees only
    # actual calls, and both "single" and 'double' quoted literals. Dynamic
    # actions (variables / f-strings) are skipped — they can't be checked
    # statically, but every action also appears as a literal at some call site.
    # Skip dirs that can't contain can() call sites (tests) or are large and
    # generated (migrations, schema modules) — keeps the scan fast. ``parts``
    # is platform-independent, unlike a "/tests/" substring check.
    skip_dirs = {"tests", "migrations", "sbom_format_schemas"}
    used: set[str] = set()
    for path in apps_root.rglob("*.py"):
        if path.name == "authz.py" or skip_dirs.intersection(path.parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not isinstance(node, ast.Call) or len(node.args) < 2:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            arg = node.args[1]
            if name == "can" and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                used.add(arg.value)

    unregistered = used - registered
    assert not unregistered, f"can() actions used in code but missing from the catalog: {sorted(unregistered)}"
    # Sanity: the scan actually found the migrated actions.
    assert {"product:manage", "component:manage", "artifact:publish"} <= used


class TestScopePermits:
    """Token action-scope grammar: a scope is a set of can() action strings.

    NULL/None scopes = full (legacy/back-compat); "*" = full; "<resource>:*" =
    every verb for that resource; "<resource>:<verb>" = that exact action.
    """

    def test_none_scope_permits_everything(self):
        assert authz._scope_permits(None, "component:manage") is True
        assert authz._scope_permits(None, "workspace:delete") is True

    def test_wildcard_permits_everything(self):
        assert authz._scope_permits(["*"], "component:manage") is True
        assert authz._scope_permits(["*"], "billing:manage") is True

    def test_exact_action_scope(self):
        assert authz._scope_permits(["sbom:read"], "sbom:read") is True
        assert authz._scope_permits(["sbom:read"], "sbom:manage") is False
        assert authz._scope_permits(["sbom:read"], "component:manage") is False

    def test_resource_bundle_scope(self):
        assert authz._scope_permits(["component:*"], "component:manage") is True
        assert authz._scope_permits(["component:*"], "component:read_internal") is True
        assert authz._scope_permits(["component:*"], "sbom:manage") is False

    def test_empty_scope_permits_nothing(self):
        assert authz._scope_permits([], "sbom:read") is False

    def test_publish_only_token(self):
        scopes = ["artifact:publish"]
        assert authz._scope_permits(scopes, "artifact:publish") is True
        assert authz._scope_permits(scopes, "component:manage") is False

    def test_is_valid_scope(self):
        assert authz.is_valid_scope("*") is True
        assert authz.is_valid_scope("component:*") is True
        assert authz.is_valid_scope("sbom:read") is True
        assert authz.is_valid_scope("artifact:publish") is True
        # invalid
        assert authz.is_valid_scope("bogus:verb") is False
        assert authz.is_valid_scope("nonresource:*") is False
        assert authz.is_valid_scope("sbom") is False
        assert authz.is_valid_scope("") is False

    def test_all_actions_matches_registered_actions(self):
        assert "component:manage" in authz.ALL_ACTIONS
        assert "artifact:publish" in authz.ALL_ACTIONS
        assert "component:access" in authz.ALL_ACTIONS  # ABAC action included


@pytest.mark.django_db
class TestTokenScopeEnforcement:
    """can() enforces an authed token's action scopes BEFORE role/ABAC checks.

    A scope can only narrow: an owner whose token is scoped to ['sbom:read'] is
    still denied 'component:manage'. An unscoped (None) token behaves as today.
    """

    def _request(self, user, scopes):
        from sbomify.apps.access_tokens.models import AccessToken

        req = HttpRequest()
        req.user = user
        req.session = {}
        req.access_token_record = AccessToken(scopes=scopes)  # unsaved; only .scopes read
        return req

    def test_scoped_token_denies_out_of_scope_action(self, workspace):
        team, component = workspace
        owner = _user("scope-owner-1")
        _member(team, owner, "owner")
        req = self._request(owner, ["sbom:read"])
        # in scope
        assert can(req, "sbom:read", component).allowed is True
        # out of scope — owner role would allow, but the token doesn't grant it
        denied = can(req, "component:manage", component)
        assert denied.allowed is False
        assert "scope" in denied.reason.lower()

    def test_unscoped_token_behaves_as_role(self, workspace):
        team, component = workspace
        owner = _user("scope-owner-2")
        _member(team, owner, "owner")
        req = self._request(owner, None)  # legacy / full
        assert can(req, "component:manage", component).allowed is True

    def test_wildcard_token_behaves_as_role(self, workspace):
        team, component = workspace
        owner = _user("scope-owner-3")
        _member(team, owner, "owner")
        req = self._request(owner, ["*"])
        assert can(req, "component:manage", component).allowed is True

    def test_scope_cannot_widen_beyond_role(self, workspace):
        """A guest with an 'all actions' token still can't manage (role gates)."""
        team, component = workspace
        guest = _user("scope-guest")
        _member(team, guest, "guest")
        req = self._request(guest, ["*"])
        assert can(req, "component:manage", component).allowed is False  # role denies

    def test_publish_scoped_bot_token(self, workspace):
        team, component = workspace
        bot = _user("scope-bot")
        _member(team, bot, "bot")
        req = self._request(bot, ["artifact:publish"])
        assert can(req, "artifact:publish", component).allowed is True
        assert can(req, "component:manage", component).allowed is False


@pytest.mark.django_db
def test_scoped_token_unknown_action_still_raises(workspace):
    """A scoped token must NOT mask a typo'd action as a denied Decision — an
    unregistered action raises UnknownActionError regardless of token scope."""
    from sbomify.apps.access_tokens.models import AccessToken

    team, component = workspace
    owner = _user("scope-unknown-action")
    _member(team, owner, "owner")
    req = HttpRequest()
    req.user = owner
    req.session = {}
    req.access_token_record = AccessToken(scopes=["sbom:read"])
    with pytest.raises(UnknownActionError):
        can(req, "component:teleport", component)


def test_read_only_preset_includes_abac_access():
    """The read-only scope must cover the ABAC component:access read path, not
    just the role-based read actions, or read-only tokens couldn't read gated
    components (can() checks scope before ABAC)."""
    assert "component:access" in authz.SCOPE_PRESETS["read_only"]
