import os
import pytest
from django.conf import settings
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team

@pytest.mark.django_db
def test_manage_team_domain(authenticated_api_client, sample_user):
    """Test adding, updating, and removing a custom domain for a workspace."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # Create a team with Business plan (allowed)
    team = Team.objects.create(name="Domain Test Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.save()

    # Add user as owner
    Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)

    base_uri = f"/api/v1/workspaces/{team.key}/domain"
    domain_name = "example.com"

    # 1. Add a domain (PUT)
    response = client.put(
        base_uri,
        {"domain": domain_name},
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["domain"] == domain_name
    assert data["validated"] is False

    # Verify in DB
    team.refresh_from_db()
    assert team.custom_domain == domain_name
    assert team.custom_domain_validated is False

    # Simulate validation
    team.custom_domain_validated = True
    team.save()

    # 2. Update domain (PUT replaces existing) - check reset
    new_domain = "new-example.com"
    response = client.put(
        base_uri,
        {"domain": new_domain},
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["domain"] == new_domain
    assert data["validated"] is False

    team.refresh_from_db()
    assert team.custom_domain == new_domain
    assert team.custom_domain_validated is False

    # Simulate validation again
    team.custom_domain_validated = True
    team.save()

    # 3. Patch domain (PATCH) - check reset
    patched_domain = "patched-example.com"
    response = client.patch(
        base_uri,
        {"domain": patched_domain},
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["domain"] == patched_domain
    assert data["validated"] is False

    team.refresh_from_db()
    assert team.custom_domain == patched_domain
    assert team.custom_domain_validated is False

    # 4. Remove domain (DELETE)
    response = client.delete(base_uri, **headers)
    assert response.status_code == 204

    team.refresh_from_db()
    assert team.custom_domain is None
    assert team.custom_domain_validated is False


@pytest.mark.django_db
def test_domain_uniqueness(authenticated_api_client, sample_user):
    """Test that domains must be globally unique."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # Create team 1
    team1 = Team.objects.create(name="Team 1", billing_plan="business")
    team1.key = number_to_random_token(team1.pk)
    team1.custom_domain = "unique.com"
    team1.save()
    Member.objects.create(team=team1, user=sample_user, role="owner")

    # Create team 2
    team2 = Team.objects.create(name="Team 2", billing_plan="business")
    team2.key = number_to_random_token(team2.pk)
    team2.save()
    Member.objects.create(team=team2, user=sample_user, role="owner")

    # Try to assign same domain to team 2
    response = client.put(
        f"/api/v1/workspaces/{team2.key}/domain",
        {"domain": "unique.com"},
        content_type="application/json",
        **headers
    )

    assert response.status_code == 400
    assert "already in use" in response.json()["detail"]


@pytest.mark.django_db
def test_domain_permissions(authenticated_api_client, guest_api_client, sample_user, guest_user):
    """Test that only owners can manage domains."""
    client, access_token = authenticated_api_client

    # Create team
    team = Team.objects.create(name="Permission Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.save()

    # Owner
    Member.objects.create(team=team, user=sample_user, role="owner")
    # Guest
    Member.objects.create(team=team, user=guest_user, role="guest")

    # Guest tries to set domain
    guest_client, guest_token = guest_api_client
    guest_headers = get_api_headers(guest_token)

    response = guest_client.put(
        f"/api/v1/workspaces/{team.key}/domain",
        {"domain": "hacker.com"},
        content_type="application/json",
        **guest_headers
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_domain_validation(authenticated_api_client, sample_user):
    """Test domain format validation (basic)."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    team = Team.objects.create(name="Validation Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.save()
    Member.objects.create(team=team, user=sample_user, role="owner")

    # Invalid domain (e.g., contains spaces or invalid chars)
    response = client.put(
        f"/api/v1/workspaces/{team.key}/domain",
        {"domain": "invalid domain.com"},
        content_type="application/json",
        **headers
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_validation_cannot_be_set_via_api(authenticated_api_client, sample_user):
    """Test that the validated flag cannot be set via API."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    team = Team.objects.create(name="Api Validation Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.save()
    Member.objects.create(team=team, user=sample_user, role="owner")

    base_uri = f"/api/v1/workspaces/{team.key}/domain"

    # Try to set validated=True in the payload
    response = client.put(
        base_uri,
        {"domain": "api-check.com", "validated": True},
        content_type="application/json",
        **headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["validated"] is False

    team.refresh_from_db()
    assert team.custom_domain_validated is False


@pytest.mark.django_db
def test_domain_feature_gating(authenticated_api_client, sample_user):
    """Test that custom domains are restricted to specific billing plans."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    # 1. Test Free Plan (Should be denied)
    team_free = Team.objects.create(name="Free Team", billing_plan="free")
    team_free.key = number_to_random_token(team_free.pk)
    team_free.save()
    Member.objects.create(team=team_free, user=sample_user, role="owner")

    response = client.put(
        f"/api/v1/workspaces/{team_free.key}/domain",
        {"domain": "free.com"},
        content_type="application/json",
        **headers
    )
    assert response.status_code == 403
    assert "Business and Enterprise" in response.json()["detail"]

    # 2. Test Community Plan (Should be denied)
    team_comm = Team.objects.create(name="Community Team", billing_plan="community")
    team_comm.key = number_to_random_token(team_comm.pk)
    team_comm.save()
    Member.objects.create(team=team_comm, user=sample_user, role="owner")

    response = client.put(
        f"/api/v1/workspaces/{team_comm.key}/domain",
        {"domain": "comm.com"},
        content_type="application/json",
        **headers
    )
    assert response.status_code == 403

    # 3. Test Business Plan (Should be allowed)
    team_biz = Team.objects.create(name="Business Team", billing_plan="business")
    team_biz.key = number_to_random_token(team_biz.pk)
    team_biz.save()
    Member.objects.create(team=team_biz, user=sample_user, role="owner")

    response = client.put(
        f"/api/v1/workspaces/{team_biz.key}/domain",
        {"domain": "biz.com"},
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200

    # 4. Test Enterprise Plan (Should be allowed)
    team_ent = Team.objects.create(name="Enterprise Team", billing_plan="enterprise")
    team_ent.key = number_to_random_token(team_ent.pk)
    team_ent.save()
    Member.objects.create(team=team_ent, user=sample_user, role="owner")

    response = client.put(
        f"/api/v1/workspaces/{team_ent.key}/domain",
        {"domain": "ent.com"},
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200
