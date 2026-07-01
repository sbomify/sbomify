import contextlib
import json
import logging
from time import time

import jwt
import pytest
from django.conf import settings
from django.test import Client, RequestFactory
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.utils import number_to_random_token, verify_item_access
from sbomify.apps.teams.fixtures import sample_team, sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member, Team

from .auth import PersonalAccessTokenAuth, optional_token_auth
from .models import AccessToken
from .utils import (
    create_personal_access_token,
    decode_personal_access_token,
    get_user_and_token_record,
    get_user_from_personal_access_token,
)


@pytest.mark.django_db
def test_access_token_encode_decode(sample_user):  # noqa: F811
    token_str = create_personal_access_token(sample_user)
    assert isinstance(token_str, str)
    assert token_str

    decoded_token = decode_personal_access_token(token_str)
    assert isinstance(decoded_token, dict)
    assert decoded_token["sub"] == str(sample_user.id)
    assert decoded_token["iss"] == "sbomify"
    assert "salt" in decoded_token

    user = get_user_from_personal_access_token(token_str)
    assert user == sample_user


@pytest.mark.django_db
def test_create_token_rejects_expires_at_without_oidc_type(sample_user):
    """Pin the round-21 invariant: ``expires_at`` and ``token_type=oidc``
    MUST be set together. Without it, a caller could mint an
    ``expires_at``-set token with default ``token_type="pat"`` — the
    decoder would skip JWT-level ``exp``/``aud`` enforcement (those
    only fire for ``token_type=oidc``) and the DB row's ``expires_at``
    would be the only revocation mechanism, defeating the
    defense-in-depth the OIDC path is built on.
    """
    from sbomify.apps.access_tokens.utils import TOKEN_TYPE_OIDC, TOKEN_TYPE_PAT

    # expires_at without oidc type → reject
    with pytest.raises(ValueError, match="must be set together"):
        create_personal_access_token(sample_user, expires_at=time() + 900)
    with pytest.raises(ValueError, match="must be set together"):
        create_personal_access_token(sample_user, expires_at=time() + 900, token_type=TOKEN_TYPE_PAT)

    # oidc type without expires_at → reject (the symmetric mistake — a
    # bot token without an exp would never expire at the JWT level)
    with pytest.raises(ValueError, match="must be set together"):
        create_personal_access_token(sample_user, token_type=TOKEN_TYPE_OIDC)

    # Both set → accepted
    token = create_personal_access_token(sample_user, expires_at=time() + 900, token_type=TOKEN_TYPE_OIDC)
    assert isinstance(token, str)

    # Neither set (plain PAT) → accepted
    token2 = create_personal_access_token(sample_user)
    assert isinstance(token2, str)


@pytest.mark.django_db
def test_expired_pat_row_is_rejected(sample_user):  # noqa: F811
    """#215: a personal access token whose DB row has expired is rejected.

    PATs carry no JWT ``exp`` (that's reserved for short-lived OIDC
    tokens); their expiry lives entirely in ``AccessToken.expires_at``
    and is enforced by step 4 of ``get_user_and_token_record``. This
    pins that an expired PAT can no longer authenticate, while a PAT
    with a future expiry still can.
    """
    from datetime import timedelta

    from django.utils import timezone

    # Expired PAT → rejected.
    expired_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(
        user=sample_user,
        encoded_token=expired_str,
        description="Expired PAT",
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    user, record = get_user_and_token_record(expired_str)
    assert user is None and record is None

    # Future-dated PAT → still authenticates.
    live_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(
        user=sample_user,
        encoded_token=live_str,
        description="Live PAT",
        expires_at=timezone.now() + timedelta(days=90),
    )
    user, record = get_user_and_token_record(live_str)
    assert user == sample_user
    assert record is not None and not record.is_expired


@pytest.mark.django_db
def test_token_with_minimal_payload(sample_user):  # noqa: F811
    # Create a token with just the required fields
    minimal_payload = {
        "sub": str(sample_user.id),
    }
    minimal_token = jwt.encode(minimal_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    # Should be able to decode and use the token
    decoded_token = decode_personal_access_token(minimal_token)
    assert isinstance(decoded_token, dict)
    assert decoded_token["sub"] == str(sample_user.id)

    user = get_user_from_personal_access_token(minimal_token)
    assert user == sample_user


@pytest.mark.django_db
def test_token_with_integer_subject(sample_user):  # noqa: F811
    # Create a token with integer subject ID
    payload = {
        "sub": int(sample_user.id),  # Force integer type
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    # Should be able to decode and use the token
    decoded_token = decode_personal_access_token(token)
    assert isinstance(decoded_token, dict)
    assert decoded_token["sub"] == str(sample_user.id)  # Should be converted to string

    user = get_user_from_personal_access_token(token)
    assert user == sample_user


@pytest.mark.django_db
def test_invalid_token_handling(sample_user):  # noqa: F811
    # Test with invalid signature
    invalid_token = jwt.encode({"sub": str(sample_user.id)}, "wrong_secret", algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(jwt.exceptions.DecodeError):
        decode_personal_access_token(invalid_token)

    assert get_user_from_personal_access_token(invalid_token) is None

    # Test with malformed token
    malformed_token = "not.a.token"
    with pytest.raises(jwt.exceptions.DecodeError):
        decode_personal_access_token(malformed_token)

    assert get_user_from_personal_access_token(malformed_token) is None

    # Test with non-existent user
    payload = {
        "iss": settings.JWT_ISSUER,
        "sub": "99999",  # Non-existent user ID
        "salt": "test",
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    assert get_user_from_personal_access_token(token) is None


# ============================================================================
# DB-verified token lookup tests
# ============================================================================


@pytest.mark.django_db
def test_db_record_required_for_auth(sample_user):  # noqa: F811
    """Token with valid JWT but no DB record -> auth returns None."""
    token_str = create_personal_access_token(sample_user)
    # Do NOT create an AccessToken DB record

    user, record = get_user_and_token_record(token_str)
    assert user is None
    assert record is None


@pytest.mark.django_db
def test_deleted_token_revocation(sample_user):  # noqa: F811
    """Create token, delete from DB, auth returns None."""
    token_str = create_personal_access_token(sample_user)
    access_token = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="Test Token")

    # Verify it works initially
    user, record = get_user_and_token_record(token_str)
    assert user == sample_user
    assert record == access_token

    # Delete from DB
    access_token.delete()

    # Should no longer work
    user, record = get_user_and_token_record(token_str)
    assert user is None
    assert record is None


@pytest.mark.django_db
def test_db_verified_lookup_returns_token_with_team(sample_user, sample_team):  # noqa: F811
    """get_user_and_token_record returns access token record with team."""
    Member.objects.create(user=sample_user, team=sample_team, role="owner", is_default_team=True)

    token_str = create_personal_access_token(sample_user)
    access_token = AccessToken.objects.create(
        user=sample_user, encoded_token=token_str, description="Scoped Token", team=sample_team
    )

    user, record = get_user_and_token_record(token_str)
    assert user == sample_user
    assert record == access_token
    assert record.team == sample_team


# ============================================================================
# PersonalAccessTokenAuth integration tests
# ============================================================================


@pytest.mark.django_db
def test_auth_sets_token_team_on_request(sample_user, sample_team):  # noqa: F811
    """PersonalAccessTokenAuth sets request.token_team for scoped tokens."""
    Member.objects.create(user=sample_user, team=sample_team, role="owner", is_default_team=True)

    token_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="Scoped Token", team=sample_team)

    factory = RequestFactory()
    request = factory.get("/")

    auth = PersonalAccessTokenAuth()
    result = auth.authenticate(request, token_str)

    assert result is not None
    assert request.token_team == sample_team
    assert request.access_token_record.team == sample_team


@pytest.mark.django_db
def test_auth_sets_token_team_none_for_unscoped(sample_user):  # noqa: F811
    """PersonalAccessTokenAuth sets request.token_team=None for unscoped tokens."""
    token_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="Unscoped Token")

    factory = RequestFactory()
    request = factory.get("/")

    auth = PersonalAccessTokenAuth()
    result = auth.authenticate(request, token_str)

    assert result is not None
    assert request.token_team is None


@pytest.mark.django_db
def test_auth_returns_none_without_db_record(sample_user):  # noqa: F811
    """PersonalAccessTokenAuth returns None when no DB record exists."""
    token_str = create_personal_access_token(sample_user)

    factory = RequestFactory()
    request = factory.get("/")

    auth = PersonalAccessTokenAuth()
    result = auth.authenticate(request, token_str)

    assert result is None


# ============================================================================
# Scoped token enforcement tests (verify_item_access)
# ============================================================================


@pytest.mark.django_db
def test_scoped_token_same_team_access(sample_user):  # noqa: F811
    """Token scoped to team A, access team A resource -> allowed."""
    team_a = Team.objects.create(name="Team A")
    team_a.key = number_to_random_token(team_a.pk)
    team_a.save()
    Member.objects.create(user=sample_user, team=team_a, role="owner", is_default_team=True)

    factory = RequestFactory()
    request = factory.get("/")
    request.user = sample_user
    request.session = {
        "user_teams": {
            team_a.key: {"role": "owner", "name": team_a.name, "is_default_team": True, "team_id": team_a.id}
        }
    }
    request.token_team = team_a

    assert verify_item_access(request, team_a, None) is True


@pytest.mark.django_db
def test_scoped_token_wrong_team_access(sample_user):  # noqa: F811
    """Token scoped to team A, access team B resource -> denied."""
    team_a = Team.objects.create(name="Team A")
    team_a.key = number_to_random_token(team_a.pk)
    team_a.save()
    team_b = Team.objects.create(name="Team B")
    team_b.key = number_to_random_token(team_b.pk)
    team_b.save()
    Member.objects.create(user=sample_user, team=team_a, role="owner", is_default_team=True)
    Member.objects.create(user=sample_user, team=team_b, role="owner")

    factory = RequestFactory()
    request = factory.get("/")
    request.user = sample_user
    request.session = {
        "user_teams": {
            team_b.key: {"role": "owner", "name": team_b.name, "is_default_team": False, "team_id": team_b.id}
        }
    }
    # Token is scoped to team A
    request.token_team = team_a

    # Trying to access team B -> denied
    assert verify_item_access(request, team_b, None) is False


@pytest.mark.django_db
def test_unscoped_legacy_token_access(sample_user):  # noqa: F811
    """Token with team=None, access any team user belongs to -> allowed."""
    team_a = Team.objects.create(name="Team A")
    team_a.key = number_to_random_token(team_a.pk)
    team_a.save()
    Member.objects.create(user=sample_user, team=team_a, role="owner", is_default_team=True)

    factory = RequestFactory()
    request = factory.get("/")
    request.user = sample_user
    request.session = {
        "user_teams": {
            team_a.key: {"role": "owner", "name": team_a.name, "is_default_team": True, "team_id": team_a.id}
        }
    }
    # Unscoped legacy token
    request.token_team = None

    assert verify_item_access(request, team_a, None) is True


# ============================================================================
# Scoped token end-to-end API tests
# ============================================================================


@pytest.mark.django_db
def test_scoped_token_create_component(sample_team_with_owner_member):  # noqa: F811
    """Scoped token can create a component without a session (exercises _get_user_team_id)."""
    member = sample_team_with_owner_member
    team = member.team
    user = member.user

    # Set up billing plan
    plan = BillingPlan.objects.create(
        key="test_plan_scoped",
        name="Test Plan",
        max_products=10,
        max_components=10,
    )
    team.billing_plan = plan.key
    team.save()

    # Create a scoped token (no session will be set up)
    token_str = create_personal_access_token(user)
    AccessToken.objects.create(user=user, encoded_token=token_str, description="Scoped Token", team=team)

    client = Client()
    url = reverse("api-1:create_component")
    payload = {"name": "Scoped Token Component"}

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_str}",
    )

    assert response.status_code == 201, f"Expected 201 but got {response.status_code}: {response.json()}"
    data = response.json()
    assert data["name"] == "Scoped Token Component"
    assert data["team_id"] == str(team.id)


# ============================================================================
# Multi-workspace token scope integration test
# ============================================================================
#
# Property under test: a user can belong to many workspaces, but a PAT scoped
# to workspace A must only grant access to workspace A. The token's scope is
# the source of truth — being a member (or even owner) of workspace B is NOT
# enough to use a workspace-A token against workspace-B resources.
#
# This is the security boundary the ``token_team`` enforcement in
# ``verify_item_access`` (sbomify/apps/core/utils.py) draws. The unit-level
# checks above (``test_scoped_token_wrong_team_access``) pin the predicate;
# this test pins the end-to-end HTTP behaviour on a real upload endpoint so
# that a regression in the wiring (e.g. a future view that bypasses
# ``verify_item_access``) shows up here.


@pytest.fixture
def _minimal_cdx_payload() -> dict:
    """Smallest valid CycloneDX 1.6 document the upload endpoint accepts.

    Real-world SBOMs are much larger, but the upload endpoint cares about
    schema validity, not size — and we want the test to fail on scope
    rejection (403), never on payload parsing.
    """
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"timestamp": "2026-01-01T00:00:00Z"},
        "components": [],
    }


@pytest.mark.django_db
def test_token_scoped_to_one_workspace_blocks_other_workspaces(
    sample_user,  # noqa: F811
    _minimal_cdx_payload,
):
    """End-to-end: a user owns two workspaces, but a PAT scoped to
    workspace A cannot reach workspace B's component.

    Mirrors the canonical multi-tenancy attack: a CI token leaks out of
    one workspace and is replayed against another workspace the same
    user happens to belong to. The token's ``team`` FK MUST be the
    deciding factor — not the user's membership.
    """
    from sbomify.apps.sboms.models import Component

    # Two distinct workspaces — same user is owner of both.
    workspace_a = Team.objects.create(name="Workspace A")
    workspace_a.key = number_to_random_token(workspace_a.pk)
    workspace_a.save()
    workspace_b = Team.objects.create(name="Workspace B")
    workspace_b.key = number_to_random_token(workspace_b.pk)
    workspace_b.save()
    Member.objects.create(user=sample_user, team=workspace_a, role="owner", is_default_team=True)
    Member.objects.create(user=sample_user, team=workspace_b, role="owner")

    # One component per workspace — the upload target.
    component_a = Component.objects.create(
        name="Component in A", team=workspace_a, component_type=Component.ComponentType.BOM
    )
    component_b = Component.objects.create(
        name="Component in B", team=workspace_b, component_type=Component.ComponentType.BOM
    )

    # PAT scoped to workspace A only.
    token_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(
        user=sample_user,
        encoded_token=token_str,
        description="PAT scoped to Workspace A",
        team=workspace_a,
    )

    client = Client()
    body = json.dumps(_minimal_cdx_payload)
    headers = {"content_type": "application/json", "HTTP_AUTHORIZATION": f"Bearer {token_str}"}

    # Workspace A: the token's home — upload must NOT be rejected as forbidden.
    # (We only assert "not 403" so this test stays focused on the scope check
    # and doesn't get coupled to validator/storage-layer details.)
    response_a = client.post(f"/api/v1/sboms/artifact/cyclonedx/{component_a.id}", data=body, **headers)
    assert response_a.status_code != 403, (
        f"Workspace-A token rejected on its own workspace's component: {response_a.status_code} {response_a.content!r}"
    )

    # Workspace B: same user, same role, but the token is NOT scoped there.
    # MUST be 403. A 200/201 here would mean the user's membership leaked
    # past the token's scope — the bug this test is here to catch.
    response_b = client.post(f"/api/v1/sboms/artifact/cyclonedx/{component_b.id}", data=body, **headers)
    assert response_b.status_code == 403, (
        f"Workspace-A token accepted upload to Workspace B's component "
        f"(membership leaked past token scope): {response_b.status_code} {response_b.content!r}"
    )


@pytest.mark.django_db
def test_token_scoped_to_workspace_a_cannot_create_in_workspace_b(
    sample_user,  # noqa: F811
):
    """Scoped-token issuance points implicit-team actions at exactly one
    workspace. A user owns workspaces A and B; the token is scoped to A.
    ``create_component`` derives the target workspace from the token's
    scope (``_get_user_team_id`` returns ``token_team.id`` first), so
    the component MUST land in A even though sample_user could legally
    create components in B via session auth.

    This pins the second half of the scope contract: not just "B is
    rejected" but "A is the only thing reachable" — a token can't be
    coerced into operating on the user's default workspace if it's
    scoped elsewhere.
    """
    workspace_a = Team.objects.create(name="Workspace A (scoped target)")
    workspace_a.key = number_to_random_token(workspace_a.pk)
    workspace_a.save()
    workspace_b = Team.objects.create(name="Workspace B (default)")
    workspace_b.key = number_to_random_token(workspace_b.pk)
    workspace_b.save()
    # B is the DEFAULT — a buggy ``_get_user_team_id`` that forgot
    # ``token_team`` would fall through to the default and create in B.
    Member.objects.create(user=sample_user, team=workspace_b, role="owner", is_default_team=True)
    Member.objects.create(user=sample_user, team=workspace_a, role="owner")

    plan_a = BillingPlan.objects.create(key="multi_scope_plan_a", name="Plan A", max_products=10, max_components=10)
    plan_b = BillingPlan.objects.create(key="multi_scope_plan_b", name="Plan B", max_products=10, max_components=10)
    workspace_a.billing_plan = plan_a.key
    workspace_a.save()
    workspace_b.billing_plan = plan_b.key
    workspace_b.save()

    token_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(
        user=sample_user,
        encoded_token=token_str,
        description="PAT scoped to Workspace A",
        team=workspace_a,
    )

    client = Client()
    response = client.post(
        reverse("api-1:create_component"),
        json.dumps({"name": "scoped-create"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_str}",
    )

    assert response.status_code == 201, response.json()
    # The component MUST belong to workspace A (the token's scope), NOT to
    # B (the user's default workspace). This is the implicit-target guarantee.
    assert response.json()["team_id"] == str(workspace_a.id), (
        f"Component created in wrong workspace: token scoped to {workspace_a.id} "
        f"but component landed in {response.json()['team_id']} (workspace B is {workspace_b.id})"
    )


# -- optional_token_auth decorator contract -----------------------------------
#
# The decorator wraps view handlers that allow anonymous access. The contract:
# no Authorization header → anonymous (handler runs); valid bearer → handler
# runs with request.user set; invalid bearer → 401 (handler must not run).
# Anything else lets clients use the endpoint as an auth probe and silently
# downgrades bad credentials to anonymous (issue: presented-but-invalid token
# was indistinguishable from no token at all).


def _make_dummy_view():
    calls: list[str] = []

    @optional_token_auth
    def view(request):
        calls.append("ran")
        user = getattr(request, "user", None)
        return getattr(user, "id", None)

    return view, calls


@pytest.mark.django_db
def test_optional_token_auth_no_header_runs_anonymously():
    """No Authorization header: handler runs, no user set on request."""
    view, calls = _make_dummy_view()
    request = RequestFactory().get("/")

    result = view(request)

    assert calls == ["ran"]
    assert result is None


@pytest.mark.django_db
def test_optional_token_auth_invalid_bearer_returns_401():
    """A presented-but-invalid bearer must 401 — never silently downgrade to anonymous.

    The decorator wraps `Operation.run` outside ninja's exception handler, so the
    contract is "return a 401 HttpResponse," not "raise an exception."
    """
    from django.http import JsonResponse

    view, calls = _make_dummy_view()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer not-a-real-token")

    response = view(request)

    assert isinstance(response, JsonResponse)
    assert response.status_code == 401
    assert json.loads(response.content) == {"detail": "Unauthorized"}
    assert calls == []  # handler must not run


@pytest.mark.django_db
def test_optional_token_auth_valid_bearer_authenticates(sample_user):  # noqa: F811
    """A valid bearer authenticates the request and the handler runs as that user."""
    token_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="t")

    view, calls = _make_dummy_view()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {token_str}")

    result = view(request)

    assert calls == ["ran"]
    assert result == sample_user.id


@pytest.mark.django_db
def test_optional_token_auth_non_bearer_header_runs_anonymously():
    """Non-Bearer schemes are ignored (treated as anonymous), not 401'd."""
    view, calls = _make_dummy_view()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz")

    result = view(request)

    assert calls == ["ran"]
    assert result is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "header",
    [
        "Bearer",  # no separator, no token
        "Bearer ",  # trailing space, empty token
        "Bearer    ",  # whitespace-only token
    ],
)
def test_optional_token_auth_malformed_bearer_returns_401(header):
    """`Bearer` with no token (any whitespace variant) is unauthorized, not anonymous."""
    from django.http import JsonResponse

    view, calls = _make_dummy_view()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=header)

    response = view(request)

    assert isinstance(response, JsonResponse)
    assert response.status_code == 401
    assert calls == []  # handler must not run


@pytest.mark.django_db
def test_optional_token_auth_multiple_spaces_extracts_token(sample_user):  # noqa: F811
    """`Bearer    <token>` (extra whitespace) must still authenticate the real token."""
    token_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="t")

    view, calls = _make_dummy_view()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer    {token_str}")

    result = view(request)

    assert calls == ["ran"]
    assert result == sample_user.id


@pytest.mark.django_db
@pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
def test_optional_token_auth_scheme_is_case_insensitive_for_invalid_token(scheme):
    """RFC 7235: auth scheme is case-insensitive. A bad token under any casing must 401,
    or the 'invalid token silently downgrades to anonymous' bug returns via lowercasing.
    """
    from django.http import JsonResponse

    view, calls = _make_dummy_view()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=f"{scheme} not-a-real-token")

    response = view(request)

    assert isinstance(response, JsonResponse)
    assert response.status_code == 401
    assert calls == []


@pytest.mark.django_db
@pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
def test_optional_token_auth_scheme_case_insensitive_for_valid_token(sample_user, scheme):  # noqa: F811
    """A valid token must authenticate regardless of scheme casing."""
    token_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="t")

    view, calls = _make_dummy_view()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=f"{scheme} {token_str}")

    result = view(request)

    assert calls == ["ran"]
    assert result == sample_user.id


# ============================================================================
# Action-scope (#215 / #1002) end-to-end enforcement
# ============================================================================
#
# Property: a token's action scopes narrow what it can do over real HTTP,
# independent of the user's role. A read-scoped token owned by a workspace
# OWNER is still rejected by a manage endpoint; an unscoped (NULL) token of the
# same owner is accepted — proving the scope gate in can() is the deciding
# factor, not the role.


@pytest.mark.django_db
def test_action_scoped_token_blocks_out_of_scope_endpoint(sample_team_with_owner_member):  # noqa: F811
    member = sample_team_with_owner_member
    team = member.team
    user = member.user
    if not team.key or len(team.key) < 9:
        team.key = number_to_random_token(team.pk)
        team.save()

    plan = BillingPlan.objects.create(key="scope_plan", name="Scope Plan", max_products=10, max_components=10)
    team.billing_plan = plan.key
    team.save()

    url = reverse("api-1:create_component")
    payload = {"name": "Scope Test Component"}

    # Token scoped to a single action (sbom:read): does NOT grant workspace:manage
    # → 403 even for an owner. (Narrower than the UI "read_only" preset bundle.)
    read_token = create_personal_access_token(user)
    AccessToken.objects.create(
        user=user, encoded_token=read_token, description="read-only", team=team, scopes=["sbom:read"]
    )
    resp_scoped = Client().post(
        url, json.dumps(payload), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {read_token}"
    )
    assert resp_scoped.status_code == 403, f"scoped token should be forbidden, got {resp_scoped.status_code}"

    # Unscoped (NULL) token of the SAME owner → allowed (201). Only the scope differs.
    full_token = create_personal_access_token(user)
    AccessToken.objects.create(user=user, encoded_token=full_token, description="full", team=team, scopes=None)
    resp_full = Client().post(
        url, json.dumps(payload), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {full_token}"
    )
    assert resp_full.status_code == 201, (
        f"unscoped token should succeed, got {resp_full.status_code}: {resp_full.content!r}"
    )


@pytest.mark.django_db
def test_create_token_form_maps_scope_presets():
    from sbomify.apps.core.authz import SCOPE_PRESETS
    from sbomify.apps.core.forms import CreateAccessTokenForm

    f = CreateAccessTokenForm({"description": "x", "scope": "full"})
    assert f.is_valid(), f.errors
    assert f.scopes() is None  # full / unscoped

    f = CreateAccessTokenForm({"description": "x", "scope": "publish"})
    assert f.is_valid(), f.errors
    assert f.scopes() == SCOPE_PRESETS["publish"]
    assert "release:create" in f.scopes()  # the publish preset covers cutting a release

    f = CreateAccessTokenForm({"description": "x", "scope": "read_only"})
    assert f.is_valid(), f.errors
    assert f.scopes() == SCOPE_PRESETS["read_only"]

    # default (no scope provided) -> full
    f = CreateAccessTokenForm({"description": "x"})
    assert f.is_valid(), f.errors
    assert f.scopes() is None


@contextlib.contextmanager
def _capture_audit(caplog):
    """Capture the non-propagating sbomify.audit.token_auth logger via caplog's handler."""
    logger = logging.getLogger("sbomify.audit.token_auth")
    logger.addHandler(caplog.handler)
    old_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(old_level)


def _token_auth_events(caplog):
    return [r for r in caplog.records if getattr(r, "event", None) == "token_auth"]


@pytest.mark.django_db
def test_token_auth_audit_success_event(
    sample_user,  # noqa: F811
    sample_team_with_owner_member,  # noqa: F811
    caplog,
):
    """#1058: a successful PAT auth emits a structured success event with IP + action."""
    token_str = create_personal_access_token(sample_user)
    rec = AccessToken.objects.create(
        user=sample_user,
        encoded_token=token_str,
        description="t",
        team=sample_team_with_owner_member.team,
    )
    with _capture_audit(caplog):
        user, record = get_user_and_token_record(token_str, source_ip="1.2.3.4", attempted_action="GET /api/x")
    assert user == sample_user
    events = _token_auth_events(caplog)
    assert len(events) == 1
    e = events[0]
    assert e.outcome == "success" and e.reason is None
    assert e.token_id == str(rec.pk)
    assert e.user_id == str(sample_user.id)
    assert e.team_id == str(sample_team_with_owner_member.team.id)
    assert e.source_ip == "1.2.3.4"
    assert e.attempted_action == "GET /api/x"
    assert e.token_fingerprint and token_str not in caplog.text
    # The fields must survive the default console formatter (in the message, not just extra).
    assert "1.2.3.4" in caplog.text and "GET /api/x" in caplog.text


@pytest.mark.django_db
def test_token_auth_audit_decode_failure(caplog):
    """#1058: an undecodable bearer emits failure(reason=decode) with a fingerprint, no token id."""
    with _capture_audit(caplog):
        user, record = get_user_and_token_record("not-a-jwt", source_ip="9.9.9.9")
    assert user is None and record is None
    e = _token_auth_events(caplog)[0]
    assert e.outcome == "failure" and e.reason == "decode"
    assert e.token_id is None and e.token_fingerprint and e.source_ip == "9.9.9.9"
    assert "not-a-jwt" not in caplog.text


@pytest.mark.django_db
def test_token_auth_audit_inactive_user(sample_user, caplog):  # noqa: F811
    """#1058: a token whose user is inactive emits failure(reason=user_inactive_or_missing)."""
    token_str = create_personal_access_token(sample_user)
    sample_user.is_active = False
    sample_user.save()
    with _capture_audit(caplog):
        user, record = get_user_and_token_record(token_str)
    assert user is None
    e = _token_auth_events(caplog)[0]
    assert e.outcome == "failure" and e.reason == "user_inactive_or_missing"
    assert e.user_id == str(sample_user.id)


@pytest.mark.django_db
def test_token_auth_audit_no_token_record(sample_user, caplog):  # noqa: F811
    """#1058: a valid token with no DB row emits failure(reason=no_token_record)."""
    token_str = create_personal_access_token(sample_user)
    with _capture_audit(caplog):
        user, record = get_user_and_token_record(token_str)
    assert user is None
    e = _token_auth_events(caplog)[0]
    assert e.outcome == "failure" and e.reason == "no_token_record"
    assert e.user_id == str(sample_user.id)


@pytest.mark.django_db
def test_token_auth_audit_expired_row(sample_user, caplog):  # noqa: F811
    """#1058: an expired DB row emits failure(reason=expired)."""
    from datetime import timedelta

    from django.utils import timezone

    token_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(
        user=sample_user,
        encoded_token=token_str,
        description="e",
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    with _capture_audit(caplog):
        user, record = get_user_and_token_record(token_str)
    assert user is None
    e = _token_auth_events(caplog)[0]
    assert e.outcome == "failure" and e.reason == "expired"


@pytest.mark.django_db
def test_token_auth_malformed_sub_is_clean_failure(caplog):
    """#1058/#1065: a token whose sub cannot be a user PK fails cleanly (no 500) and audits."""
    bad = jwt.encode(
        {"sub": "not-a-valid-pk", "token_type": "pat"}, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    with _capture_audit(caplog):
        user, record = get_user_and_token_record(bad)
    assert user is None and record is None
    e = _token_auth_events(caplog)[0]
    assert e.outcome == "failure" and e.reason == "user_inactive_or_missing"


@pytest.mark.django_db
def test_token_auth_audit_team_id_null_for_teamless_token(sample_user, caplog):  # noqa: F811
    """#1058: a token with no team emits team_id as None (JSON null), not the string 'None'."""
    token_str = create_personal_access_token(sample_user)
    AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="no-team")
    with _capture_audit(caplog):
        user, record = get_user_and_token_record(token_str)
    assert user == sample_user
    e = _token_auth_events(caplog)[0]
    assert e.outcome == "success"
    assert e.team_id is None


@pytest.mark.django_db
def test_token_auth_audit_oidc_jwt_expiry_is_expired_not_decode(sample_user, caplog):  # noqa: F811
    """#1058: an OIDC token past its JWT exp audits as reason=expired (INFO), not decode."""
    from sbomify.apps.access_tokens.utils import TOKEN_TYPE_OIDC

    expired_oidc = create_personal_access_token(sample_user, expires_at=time() - 100, token_type=TOKEN_TYPE_OIDC)
    with _capture_audit(caplog):
        user, record = get_user_and_token_record(expired_oidc)
    assert user is None and record is None
    e = _token_auth_events(caplog)[0]
    assert e.outcome == "failure" and e.reason == "expired"


# ---------------------------------------------------------------------------
# #1044: AccessToken.last_used_at usage tracking
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_last_used_at_stamped_on_use(sample_user):  # noqa: F811
    """A valid authenticated request stamps last_used_at on the token row."""
    token_str = create_personal_access_token(sample_user)
    record = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="t")
    assert record.last_used_at is None

    user, returned = get_user_and_token_record(token_str)

    assert user == sample_user
    record.refresh_from_db()
    assert record.last_used_at is not None
    # The in-memory record handed to the caller is also fresh (not stale).
    assert returned.last_used_at is not None


@pytest.mark.django_db
def test_last_used_at_throttled_within_window(sample_user, settings):  # noqa: F811
    """A second use inside the throttle window does NOT write again."""
    from datetime import timedelta

    from django.utils import timezone

    settings.ACCESS_TOKEN_LAST_USED_THROTTLE_SECONDS = 300
    token_str = create_personal_access_token(sample_user)
    recent = timezone.now() - timedelta(seconds=30)  # well inside the 300s window
    record = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="t", last_used_at=recent)

    _, returned = get_user_and_token_record(token_str)

    record.refresh_from_db()
    assert record.last_used_at == recent  # unchanged — throttled (no DB write)
    # The in-memory record is only refreshed when this request actually wrote it.
    assert returned.last_used_at == recent


@pytest.mark.django_db
def test_last_used_at_refreshed_after_window(sample_user, settings):  # noqa: F811
    """Once last_used_at is older than the window, the next use refreshes it."""
    from datetime import timedelta

    from django.utils import timezone

    settings.ACCESS_TOKEN_LAST_USED_THROTTLE_SECONDS = 300
    token_str = create_personal_access_token(sample_user)
    stale = timezone.now() - timedelta(seconds=400)  # older than the 300s window
    record = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="t", last_used_at=stale)

    get_user_and_token_record(token_str)

    record.refresh_from_db()
    assert record.last_used_at > stale


@pytest.mark.django_db
def test_last_used_at_not_stamped_for_expired_token(sample_user):  # noqa: F811
    """An expired token is rejected and must NOT be stamped."""
    from datetime import timedelta

    from django.utils import timezone

    token_str = create_personal_access_token(sample_user)
    record = AccessToken.objects.create(
        user=sample_user,
        encoded_token=token_str,
        description="expired",
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    user, returned = get_user_and_token_record(token_str)

    assert user is None and returned is None
    record.refresh_from_db()
    assert record.last_used_at is None


@pytest.mark.django_db
def test_last_used_at_stamped_for_oidc_token(sample_user):  # noqa: F811
    """OIDC short-lived tokens flow through the same chokepoint and get stamped."""
    from sbomify.apps.access_tokens.utils import TOKEN_TYPE_OIDC

    token_str = create_personal_access_token(sample_user, expires_at=time() + 900, token_type=TOKEN_TYPE_OIDC)
    record = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="oidc")

    get_user_and_token_record(token_str)

    record.refresh_from_db()
    assert record.last_used_at is not None


@pytest.mark.django_db
def test_last_used_at_refreshed_when_future_dated(sample_user, settings):  # noqa: F811
    """A future-dated last_used_at (clock skew / manual edit) is treated as stale
    and refreshed, not frozen forever."""
    from datetime import timedelta

    from django.utils import timezone

    settings.ACCESS_TOKEN_LAST_USED_THROTTLE_SECONDS = 300
    token_str = create_personal_access_token(sample_user)
    future = timezone.now() + timedelta(days=1)
    record = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="t", last_used_at=future)

    get_user_and_token_record(token_str)

    record.refresh_from_db()
    assert record.last_used_at < future  # refreshed to ~now, not stuck in the future


@pytest.mark.django_db
def test_last_used_at_not_clobbered_by_slight_future(sample_user, settings):  # noqa: F811
    """A value slightly ahead of now (a concurrent worker's lead clock, within the
    throttle window) is left alone — we must never write an earlier time back."""
    from datetime import timedelta

    from django.utils import timezone

    settings.ACCESS_TOKEN_LAST_USED_THROTTLE_SECONDS = 300
    token_str = create_personal_access_token(sample_user)
    slightly_ahead = timezone.now() + timedelta(seconds=10)  # within the 300s window
    record = AccessToken.objects.create(
        user=sample_user, encoded_token=token_str, description="t", last_used_at=slightly_ahead
    )

    get_user_and_token_record(token_str)

    record.refresh_from_db()
    assert record.last_used_at == slightly_ahead  # not clobbered with an earlier time


@pytest.mark.django_db
def test_last_used_at_skew_tolerated_even_at_zero_throttle(sample_user, settings):  # noqa: F811
    """Forward-skew tolerance is independent of the throttle window: even with
    throttle=0 (write-every-request), a slightly-ahead concurrent timestamp is
    not clobbered with an earlier now."""
    from datetime import timedelta

    from django.utils import timezone

    settings.ACCESS_TOKEN_LAST_USED_THROTTLE_SECONDS = 0
    token_str = create_personal_access_token(sample_user)
    slightly_ahead = timezone.now() + timedelta(seconds=10)  # within the fixed skew tolerance
    record = AccessToken.objects.create(
        user=sample_user, encoded_token=token_str, description="t", last_used_at=slightly_ahead
    )

    get_user_and_token_record(token_str)

    record.refresh_from_db()
    assert record.last_used_at == slightly_ahead  # not clobbered despite throttle=0


def test_access_token_rate_throttle_per_token():
    """#1060: a token is limited per its rate, and two tokens have independent budgets."""
    from types import SimpleNamespace

    from django.core.cache import cache

    from sbomify.apps.access_tokens.throttling import AccessTokenRateThrottle

    cache.clear()
    rf = RequestFactory()
    throttle = AccessTokenRateThrottle(rate="2/min")

    def req(pk):
        r = rf.get("/api/v1/x")
        r.access_token_record = SimpleNamespace(pk=pk)
        return r

    assert throttle.allow_request(req(101)) is True
    assert throttle.allow_request(req(101)) is True
    assert throttle.allow_request(req(101)) is False  # third request over the 2/min limit
    assert throttle.allow_request(req(202)) is True  # a different token keeps its own budget


def test_access_token_rate_throttle_skips_anonymous():
    """#1060: requests with no resolved token record (session/anonymous) are not throttled."""
    from sbomify.apps.access_tokens.throttling import AccessTokenRateThrottle

    rf = RequestFactory()
    throttle = AccessTokenRateThrottle(rate="1/min")
    r = rf.get("/api/v1/x")
    assert throttle.get_cache_key(r) is None
    assert throttle.allow_request(r) is True
    assert throttle.allow_request(r) is True


def test_throttled_handler_sets_retry_after():
    """#1060: the 429 response carries Retry-After from the Throttled wait, and omits it when None."""
    from ninja.errors import Throttled

    from sbomify.apis import _on_throttled

    req = RequestFactory().get("/api/v1/x")
    resp = _on_throttled(req, Throttled(wait=42))
    assert resp.status_code == 429
    assert resp["Retry-After"] == "42"

    # Fractional waits round UP (never truncate to 0), so clients don't retry too early.
    assert _on_throttled(req, Throttled(wait=0.4))["Retry-After"] == "1"
    assert _on_throttled(req, Throttled(wait=5.1))["Retry-After"] == "6"

    resp_no_wait = _on_throttled(req, Throttled(wait=None))
    assert resp_no_wait.status_code == 429
    assert "Retry-After" not in resp_no_wait


def test_heavy_throttle_independent_budget_and_distinct_key():
    """#1070: the heavy throttle limits independently and never shares the global window."""
    from types import SimpleNamespace

    from django.core.cache import cache

    from sbomify.apps.access_tokens.throttling import AccessTokenHeavyRateThrottle, AccessTokenRateThrottle

    cache.clear()
    rf = RequestFactory()

    def req(pk):
        r = rf.get("/api/v1/x")
        r.access_token_record = SimpleNamespace(pk=pk)
        return r

    heavy = AccessTokenHeavyRateThrottle(rate="2/min")
    global_throttle = AccessTokenRateThrottle(rate="2/min")
    # Distinct cache key is the central gotcha — a shared key would corrupt both windows.
    assert global_throttle.get_cache_key(req(7)) != heavy.get_cache_key(req(7))
    assert heavy.allow_request(req(7)) is True
    assert heavy.allow_request(req(7)) is True
    assert heavy.allow_request(req(7)) is False  # heavy limit hit
    # The global window for the SAME token is untouched by the heavy throttle.
    assert global_throttle.allow_request(req(7)) is True
    assert global_throttle.allow_request(req(7)) is True


def test_heavy_throttle_skips_anonymous():
    """#1070: a request with no token record (session/anonymous) is not throttled."""
    from sbomify.apps.access_tokens.throttling import AccessTokenHeavyRateThrottle

    r = RequestFactory().get("/api/v1/x")
    assert AccessTokenHeavyRateThrottle(rate="1/min").get_cache_key(r) is None


def test_upload_endpoints_carry_global_and_heavy_throttles():
    """#1070: the PAT upload endpoints carry BOTH throttles (per-op replaces the global)."""
    from sbomify.apis import api

    found = {}
    for _prefix, router in api._routers:
        for path, pv in router.path_operations.items():
            if path in ("/artifact/cyclonedx/{component_id}", "/artifact/spdx/{component_id}"):
                for op in pv.operations:
                    found[path] = [type(t).__name__ for t in op.throttle_objects]
    assert found["/artifact/cyclonedx/{component_id}"] == ["AccessTokenRateThrottle", "AccessTokenHeavyRateThrottle"]
    assert found["/artifact/spdx/{component_id}"] == ["AccessTokenRateThrottle", "AccessTokenHeavyRateThrottle"]
