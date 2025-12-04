import pytest

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
    domain_name = "app.example.com"

    # 1. Add a domain (PUT)
    response = client.put(base_uri, {"domain": domain_name}, content_type="application/json", **headers)
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
    new_domain = "new-app.example.com"
    response = client.put(base_uri, {"domain": new_domain}, content_type="application/json", **headers)
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
    patched_domain = "patched.example.com"
    response = client.patch(base_uri, {"domain": patched_domain}, content_type="application/json", **headers)
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
    team1.custom_domain = "team1.unique.com"
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
        {"domain": "team1.unique.com"},
        content_type="application/json",
        **headers,
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
        {"domain": "hacker.example.com"},
        content_type="application/json",
        **guest_headers,
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
        **headers,
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
        base_uri, {"domain": "api-check.com", "validated": True}, content_type="application/json", **headers
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
        {"domain": "app.free.com"},
        content_type="application/json",
        **headers,
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
        {"domain": "app.comm.com"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 403

    # 3. Test Business Plan (Should be allowed)
    team_biz = Team.objects.create(name="Business Team", billing_plan="business")
    team_biz.key = number_to_random_token(team_biz.pk)
    team_biz.save()
    Member.objects.create(team=team_biz, user=sample_user, role="owner")

    response = client.put(
        f"/api/v1/workspaces/{team_biz.key}/domain",
        {"domain": "app.biz.com"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200

    # 4. Test Enterprise Plan (Should be allowed)
    team_ent = Team.objects.create(name="Enterprise Team", billing_plan="enterprise")
    team_ent.key = number_to_random_token(team_ent.pk)
    team_ent.save()
    Member.objects.create(team=team_ent, user=sample_user, role="owner")

    response = client.put(
        f"/api/v1/workspaces/{team_ent.key}/domain",
        {"domain": "app.ent.com"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_caddy_ask_endpoint_allowed_domain(client):
    """
    Test that the Caddy on-demand TLS ask endpoint returns 200 OK for allowed domains.

    Per Caddy documentation: The ask endpoint receives ?domain=example.com and should
    return 200 OK if the domain is allowed to get a certificate.
    """
    # Create a team with Business plan and custom domain
    team = Team.objects.create(name="Business Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = "app.example.com"
    team.save()

    # Caddy will call with ?domain= query parameter
    response = client.get("/api/v1/internal/domains?domain=app.example.com")
    assert response.status_code == 200


@pytest.mark.django_db
def test_caddy_ask_endpoint_denied_domain(client):
    """
    Test that the Caddy on-demand TLS ask endpoint returns 404 for unknown domains.

    Per Caddy documentation: The ask endpoint should return non-200 status if the
    domain should NOT get a certificate.
    """
    # No domain configured in database
    response = client.get("/api/v1/internal/domains?domain=unknown.example.com")
    assert response.status_code == 404


@pytest.mark.django_db
def test_caddy_ask_endpoint_case_insensitive(client):
    """Test that domain checking is case-insensitive."""
    team = Team.objects.create(name="Business Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = "app.example.com"
    team.save()

    # Test with different case variations
    response = client.get("/api/v1/internal/domains?domain=APP.EXAMPLE.COM")
    assert response.status_code == 200

    response = client.get("/api/v1/internal/domains?domain=App.Example.Com")
    assert response.status_code == 200


@pytest.mark.django_db
def test_caddy_ask_endpoint_validation_status_irrelevant(client):
    """
    Test that domain validation status doesn't affect certificate issuance approval.

    Validation happens AFTER certificate is issued, so both validated and unvalidated
    domains should return 200 OK.
    """
    # Unvalidated domain
    team1 = Team.objects.create(name="Team 1", billing_plan="business")
    team1.key = number_to_random_token(team1.pk)
    team1.custom_domain = "unvalidated.example.com"
    team1.custom_domain_validated = False
    team1.save()

    # Validated domain
    team2 = Team.objects.create(name="Team 2", billing_plan="business")
    team2.key = number_to_random_token(team2.pk)
    team2.custom_domain = "validated.example.com"
    team2.custom_domain_validated = True
    team2.save()

    # Both should be allowed
    response = client.get("/api/v1/internal/domains?domain=unvalidated.example.com")
    assert response.status_code == 200

    response = client.get("/api/v1/internal/domains?domain=validated.example.com")
    assert response.status_code == 200


@pytest.mark.django_db
def test_caddy_ask_endpoint_sanitizes_input(client):
    """
    Test that the endpoint properly sanitizes domain input using urlparse.

    This prevents issues where malicious input includes protocols, ports, or paths.
    """
    team = Team.objects.create(name="Business Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = "app.example.com"
    team.save()

    # Test with protocol prefix - should be stripped
    response = client.get("/api/v1/internal/domains?domain=https://app.example.com")
    assert response.status_code == 200

    response = client.get("/api/v1/internal/domains?domain=http://app.example.com")
    assert response.status_code == 200

    # Test with port - should be stripped
    response = client.get("/api/v1/internal/domains?domain=app.example.com:8000")
    assert response.status_code == 200

    # Test with path - should be stripped
    response = client.get("/api/v1/internal/domains?domain=app.example.com/some/path")
    assert response.status_code == 200

    # Test with query string - should be stripped
    response = client.get("/api/v1/internal/domains?domain=app.example.com?query=param")
    assert response.status_code == 200

    # Test with full URL - should extract hostname
    response = client.get("/api/v1/internal/domains?domain=https://app.example.com:443/path?query=1")
    assert response.status_code == 200

    # Test that wrong domain still returns 404 even with sanitization
    response = client.get("/api/v1/internal/domains?domain=https://wrong.example.com:8000/path")
    assert response.status_code == 404


@pytest.mark.django_db
def test_caddy_ask_endpoint_filters_by_billing_plan(client):
    """
    Test that only Business and Enterprise plan domains are allowed certificates.
    """
    # Business plan - should be allowed
    team_business = Team.objects.create(name="Business Team", billing_plan="business")
    team_business.key = number_to_random_token(team_business.pk)
    team_business.custom_domain = "business.example.com"
    team_business.save()

    # Enterprise plan - should be allowed
    team_enterprise = Team.objects.create(name="Enterprise Team", billing_plan="enterprise")
    team_enterprise.key = number_to_random_token(team_enterprise.pk)
    team_enterprise.custom_domain = "enterprise.example.com"
    team_enterprise.save()

    # Free plan - should be denied
    team_free = Team.objects.create(name="Free Team", billing_plan="free")
    team_free.key = number_to_random_token(team_free.pk)
    team_free.custom_domain = "free.example.com"
    team_free.save()

    # Community plan - should be denied
    team_community = Team.objects.create(name="Community Team", billing_plan="community")
    team_community.key = number_to_random_token(team_community.pk)
    team_community.custom_domain = "community.example.com"
    team_community.save()

    # Test allowed domains
    response = client.get("/api/v1/internal/domains?domain=business.example.com")
    assert response.status_code == 200

    response = client.get("/api/v1/internal/domains?domain=enterprise.example.com")
    assert response.status_code == 200

    # Test denied domains
    response = client.get("/api/v1/internal/domains?domain=free.example.com")
    assert response.status_code == 404

    response = client.get("/api/v1/internal/domains?domain=community.example.com")
    assert response.status_code == 404
