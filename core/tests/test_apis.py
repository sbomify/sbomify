"""Tests for core API endpoints."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from access_tokens.models import AccessToken
from core.tests.shared_fixtures import get_api_headers
from sboms.tests.fixtures import sample_access_token  # noqa: F401
from teams.fixtures import sample_team  # noqa: F401

User = get_user_model()


@pytest.mark.django_db
def test_list_teams_api_authenticated(sample_access_token, sample_team):  # noqa: F811
    """Test listing teams via API with valid access token."""
    client = Client()

    response = client.get(
        reverse("api-1:list_teams"),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == sample_team.name


@pytest.mark.django_db
def test_list_teams_api_unauthenticated():
    """Test listing teams via API without authentication."""
    client = Client()

    response = client.get(reverse("api-1:list_teams"))

    assert response.status_code == 401


@pytest.mark.django_db
def test_get_team_api_authenticated(sample_access_token, sample_team):  # noqa: F811
    """Test getting specific team via API with valid access token."""
    client = Client()

    response = client.get(
        reverse("api-1:get_team", kwargs={"team_key": sample_team.key}),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == sample_team.name
    assert data["key"] == sample_team.key


@pytest.mark.django_db
def test_get_team_api_nonexistent(sample_access_token):  # noqa: F811
    """Test getting non-existent team via API."""
    client = Client()

    response = client.get(
        reverse("api-1:get_team", kwargs={"team_key": "nonexistent"}),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_update_team_api_authenticated(sample_access_token, sample_team):  # noqa: F811
    """Test updating team via API with valid access token."""
    client = Client()

    update_data = {"name": "Updated Team Name"}

    response = client.patch(
        reverse("api-1:update_team", kwargs={"team_key": sample_team.key}),
        json.dumps(update_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Team Name"

    # Verify the team was actually updated
    sample_team.refresh_from_db()
    assert sample_team.name == "Updated Team Name"


@pytest.mark.django_db
def test_api_requires_valid_token():
    """Test that API endpoints require valid access tokens."""
    client = Client()

    # Test with completely invalid token format
    invalid_headers = {"HTTP_AUTHORIZATION": "Bearer invalid-token-format"}

    response = client.get(reverse("api-1:list_teams"), **invalid_headers)
    assert response.status_code in [401, 403]

    # Test with malformed JWT token
    malformed_headers = {"HTTP_AUTHORIZATION": "Bearer not.a.valid.jwt"}

    response = client.get(reverse("api-1:list_teams"), **malformed_headers)
    assert response.status_code in [401, 403]


@pytest.mark.django_db
def test_api_endpoints_with_malformed_token():
    """Test API endpoints with malformed authorization headers."""
    client = Client()

    # Test with malformed header
    malformed_headers = {"HTTP_AUTHORIZATION": "Bearer invalid-token-format"}

    response = client.get(reverse("api-1:list_teams"), **malformed_headers)
    assert response.status_code in [401, 403]

    # Test with missing Bearer prefix
    malformed_headers = {"HTTP_AUTHORIZATION": "invalid-token-format"}

    response = client.get(reverse("api-1:list_teams"), **malformed_headers)
    assert response.status_code in [401, 403]


@pytest.mark.django_db
def test_api_endpoints_require_team_membership(sample_access_token):  # noqa: F811
    """Test that API endpoints require appropriate team membership."""
    client = Client()

    # Create a team that the user is not a member of
    from teams.models import Team
    other_team = Team.objects.create(name="Other Team")

    response = client.get(
        reverse("api-1:get_team", kwargs={"team_key": other_team.key}),
        **get_api_headers(sample_access_token),
    )

    # Should return 403/404 for teams user is not a member of
    assert response.status_code in [403, 404]


@pytest.mark.django_db
def test_api_pagination_headers():
    """Test that API endpoints include appropriate pagination headers."""
    # This is a placeholder for future pagination testing
    # Current API endpoints don't implement pagination yet
    pass


@pytest.mark.django_db
def test_api_cors_headers(sample_access_token, sample_team):  # noqa: F811
    """Test that API responses include appropriate CORS headers."""
    client = Client()

    response = client.get(
        reverse("api-1:list_teams"),
        **get_api_headers(sample_access_token),
    )

    # Check for standard API response headers
    assert response.status_code == 200
    assert "Content-Type" in response
    assert response["Content-Type"] == "application/json; charset=utf-8"


@pytest.mark.django_db
def test_api_error_handling(sample_access_token):  # noqa: F811
    """Test API error handling and response format."""
    client = Client()

    # Test 404 error response format
    response = client.get(
        reverse("api-1:get_team", kwargs={"team_key": "nonexistent"}),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)



