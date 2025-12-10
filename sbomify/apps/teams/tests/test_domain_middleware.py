import pytest


@pytest.mark.django_db
def test_dynamic_host_validation_middleware(client):
    """Test that the DynamicHostValidationMiddleware works correctly."""
    from django.core.cache import cache

    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Team

    # 1. Test static hosts - should be allowed
    response = client.get("/", HTTP_HOST="localhost")
    assert response.status_code != 400, "Static host 'localhost' should be allowed"

    response = client.get("/", HTTP_HOST="testserver")
    assert response.status_code != 400, "Static host 'testserver' should be allowed"

    # 2. Test invalid domain (not in DB) - should be rejected
    response = client.get("/", HTTP_HOST="random-invalid-domain.com")
    assert response.status_code == 400, "Invalid domain should be rejected with 400"
    assert b"Invalid host header" in response.content

    # 3. Test custom domain (not yet in DB) - should be rejected
    custom_domain = "app.custom-customer.com"
    response = client.get("/", HTTP_HOST=custom_domain)
    assert response.status_code == 400, "Custom domain not in DB should be rejected"

    # 4. Add domain to DB
    team = Team.objects.create(name="Host Test Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = custom_domain
    team.save()

    # Clear cache after adding domain
    cache.delete(f"allowed_host:{custom_domain}")

    # 5. Now should be allowed (returns 200 for well-known endpoint)
    response = client.get("/.well-known/com.sbomify.domain-check", HTTP_HOST=custom_domain)
    assert response.status_code == 200, "Custom domain in DB should be allowed"

    # 6. Test with port - should strip port and validate hostname
    # (Note: / redirects to login (302) but that's OK - it passed middleware validation)
    response = client.get("/", HTTP_HOST=f"{custom_domain}:8000")
    assert response.status_code != 400, "Domain with port should work (port stripped)"

    # 7. Test caching - second request should hit cache
    response = client.get("/.well-known/com.sbomify.domain-check", HTTP_HOST=custom_domain)
    assert response.status_code == 200, "Cached domain should be allowed"


@pytest.mark.django_db
def test_domain_check_endpoint_validates_domain():
    """
    Test that the .well-known/com.sbomify.domain-check endpoint validates domains.

    This test directly calls the view function to test the validation logic,
    bypassing ALLOWED_HOSTS checks which are tested separately.
    """
    import json

    from django.http import HttpRequest

    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Team
    from sbomify.apps.teams.urls import domain_check

    # Create team with unvalidated domain
    team = Team.objects.create(name="Check Endpoint Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = "validated.example.com"
    team.custom_domain_validated = False
    team.save()

    # Create mock request with the custom domain as Host
    request = HttpRequest()
    request.META = {"HTTP_HOST": "validated.example.com"}

    # Call the view directly
    response = domain_check(request)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"

    # Check response structure
    data = json.loads(response.content)
    assert data["ok"] is True
    assert data["service"] == "sbomify"
    assert data["domain"] == "validated.example.com"
    assert "ts" in data
    assert "region" in data

    # Check DB - should be validated now by the domain-check endpoint
    team.refresh_from_db()
    assert team.custom_domain_validated is True
    assert team.custom_domain_last_checked_at is not None
    assert team.custom_domain_verification_failures == 0


@pytest.mark.django_db
def test_custom_domain_http_request_through_middleware(client):
    """
    Test that custom domains work with actual HTTP requests through middleware.

    This verifies the fix for the production issue where domains in the database
    were being rejected due to Django 4.0+ incompatibility with custom ALLOWED_HOSTS classes.
    """
    import json

    from django.core.cache import cache

    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Team

    # Create team with unvalidated custom domain
    custom_domain = "test-production.example.com"
    team = Team.objects.create(name="HTTP Request Test Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = custom_domain
    team.custom_domain_validated = False
    team.save()

    # Clear cache to force DB lookup
    cache.delete(f"allowed_host:{custom_domain}")

    # Verify domain is in database
    assert Team.objects.filter(custom_domain=custom_domain).exists()

    # Make actual HTTP request through Django test client with custom Host header
    # This simulates what happens in production when a request comes in
    response = client.get(
        "/.well-known/com.sbomify.domain-check",
        HTTP_HOST=custom_domain,
    )

    # Should get 200 - middleware allows domain that exists in DB
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. "
        f"Middleware should allow domain that exists in database."
    )

    # Verify response is valid JSON
    data = json.loads(response.content)
    assert data["ok"] is True
    assert data["domain"] == custom_domain

    # Verify domain was validated by the endpoint
    team.refresh_from_db()
    assert team.custom_domain_validated is True


@pytest.mark.django_db
def test_middleware_rejects_invalid_domains(client):
    """Test that middleware properly rejects domains not in the database."""
    from django.core.cache import cache

    invalid_domain = "definitely-not-in-database.example.com"

    # Clear any potential cache
    cache.delete(f"allowed_host:{invalid_domain}")

    # Request with invalid domain should be rejected
    response = client.get("/", HTTP_HOST=invalid_domain)

    assert response.status_code == 400, "Invalid domain should be rejected with 400"
    assert b"Invalid host header" in response.content


@pytest.mark.django_db
def test_middleware_caching_behavior(client):
    """Test that middleware properly caches validation results."""
    from django.core.cache import cache

    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Team

    custom_domain = "caching-test.example.com"

    # Create team with domain
    team = Team.objects.create(name="Cache Test Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = custom_domain
    team.save()

    # Clear cache
    cache.delete(f"allowed_host:{custom_domain}")

    # First request should hit database and pass middleware
    response1 = client.get("/.well-known/com.sbomify.domain-check", HTTP_HOST=custom_domain)
    assert response1.status_code == 200

    # Second request should hit cache and also work
    response2 = client.get("/.well-known/com.sbomify.domain-check", HTTP_HOST=custom_domain)
    assert response2.status_code == 200
