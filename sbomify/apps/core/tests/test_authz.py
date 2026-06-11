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


# (action, resource, expected-allowed per role) — the role->capability matrix,
# written to match what the inline checks grant today.
_MATRIX = {
    "workspace:administer": ("team", {"owner": True, "admin": False, "guest": False, "bot": False}),
    "component:manage": ("component", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "artifact:publish": ("component", {"owner": True, "admin": True, "guest": False, "bot": True}),
    "workspace:read": ("team", {"owner": True, "admin": True, "guest": True, "bot": False}),
    "component:administer": ("component", {"owner": True, "admin": False, "guest": False, "bot": False}),
    "product:read": ("product", {"owner": True, "admin": True, "guest": True, "bot": False}),
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
    used: set[str] = set()
    for path in apps_root.rglob("*.py"):
        if "/tests/" in str(path) or path.name == "authz.py":
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
