import json

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

from .auth import PersonalAccessTokenAuth
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
        max_projects=10,
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
