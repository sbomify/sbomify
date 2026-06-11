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
from sbomify.apps.core.models import Component
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


# (action, resource, expected-allowed per role) — the role->capability matrix,
# written to match what the inline checks grant today.
_MATRIX = {
    "workspace:administer": ("team", {"owner": True, "admin": False, "guest": False, "bot": False}),
    "component:manage": ("component", {"owner": True, "admin": True, "guest": False, "bot": False}),
    "artifact:publish": ("component", {"owner": True, "admin": True, "guest": False, "bot": True}),
    "workspace:read": ("team", {"owner": True, "admin": True, "guest": True, "bot": False}),
}
_CASES = [(a, role, exp[role]) for a, (_res, exp) in _MATRIX.items() for role in ("owner", "admin", "guest", "bot")]


@pytest.mark.django_db
@pytest.mark.parametrize("action,role,expected", _CASES)
def test_role_capability_matrix(workspace, action, role, expected):
    team, component = workspace
    resource = team if _MATRIX[action][0] == "team" else component
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
    resource = team if _MATRIX[action][0] == "team" else component
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
