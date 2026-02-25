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
def test_domain_check_endpoint_validates_domain(client):
    """
    Test that requesting .well-known/com.sbomify.domain-check validates the domain.

    Validation is performed by CustomDomainContextMiddleware before the view runs.
    This test sends a real request through the middleware to verify the full flow.
    """
    import json

    from django.core.cache import cache

    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Team

    custom_domain = "validated.example.com"

    # Create team with unvalidated domain
    team = Team.objects.create(name="Check Endpoint Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = custom_domain
    team.custom_domain_validated = False
    team.save()

    # Clear cache to force DB lookup in middleware
    cache.delete(f"allowed_host:{custom_domain}")

    # Make request through middleware — middleware validates the domain
    response = client.get(
        "/.well-known/com.sbomify.domain-check",
        HTTP_HOST=custom_domain,
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"

    # Check response structure
    data = json.loads(response.content)
    assert data["ok"] is True
    assert data["service"] == "sbomify"
    assert data["domain"] == custom_domain
    assert "ts" in data
    assert "region" in data

    # Check DB - should be validated by the middleware
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
        f"Expected 200, got {response.status_code}. Middleware should allow domain that exists in database."
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


def test_normalize_host_handles_ipv6():
    """Test that normalize_host properly handles IPv6 addresses."""
    from sbomify.apps.teams.utils import normalize_host

    # IPv6 addresses with ports - extracts correctly without the brackets
    assert normalize_host("[::1]:8000") == "::1"
    assert normalize_host("[2001:db8::1]:8000") == "2001:db8::1"
    # Note: urlparse doesn't normalize IPv6 format, just extracts it
    assert normalize_host("[2001:0db8:85a3:0000:0000:8a2e:0370:7334]:443") == "2001:0db8:85a3:0000:0000:8a2e:0370:7334"

    # IPv6 addresses without ports
    assert normalize_host("[::1]") == "::1"
    assert normalize_host("[2001:db8::1]") == "2001:db8::1"

    # Regular domains still work
    assert normalize_host("example.com") == "example.com"
    assert normalize_host("example.com:8000") == "example.com"
    assert normalize_host("Example.COM:443") == "example.com"

    # Localhost
    assert normalize_host("localhost") == "localhost"
    assert normalize_host("localhost:8000") == "localhost"
    assert normalize_host("127.0.0.1:8000") == "127.0.0.1"


@pytest.mark.django_db
def test_middleware_rejects_ip_addresses(client):
    """
    Test that middleware rejects IP addresses for custom domains.

    Security: Only FQDNs should be allowed as custom domains, not IP addresses.
    Static hosts (localhost, 127.0.0.1) are allowed for internal use.
    """
    from django.core.cache import cache

    # Static IPs should still work (localhost, 127.0.0.1)
    response = client.get("/", HTTP_HOST="127.0.0.1")
    assert response.status_code != 400, "Static IP 127.0.0.1 should be allowed"

    # But other IPv4 addresses should be rejected
    cache.delete("allowed_host:192.168.1.100")
    response = client.get("/", HTTP_HOST="192.168.1.100")
    assert response.status_code == 400, "Non-static IPv4 should be rejected"
    assert b"Invalid host header" in response.content

    # IPv6 addresses should be rejected (except ::1 which is not in our static list currently)
    cache.delete("allowed_host:2001:db8::1")
    response = client.get("/", HTTP_HOST="[2001:db8::1]")
    assert response.status_code == 400, "IPv6 addresses should be rejected"
    assert b"Invalid host header" in response.content


@pytest.mark.django_db
def test_middleware_handles_malformed_host_headers(client):
    """
    Test that middleware gracefully handles malformed host headers.

    This tests the fix for XSS attack attempts where attackers send malformed
    X-Forwarded-Host headers containing script tags or other invalid characters.

    Django's request.get_host() validates hostname format per RFC 1034/1035 and
    raises DisallowedHost for invalid hostnames. The middleware should catch this
    and return a clean 400 response without raising an exception to Sentry.
    """
    # Test XSS attack pattern in Host header (script tags)
    malformed_hosts = [
        'xss.test"></script><script>alert(1)</script>',
        "test<script>alert('xss')</script>.com",
        'test.com"><img src=x onerror=alert(1)>',
        "test'OR'1'='1.com",  # SQL injection attempt
        "test\x00null.com",  # Null byte injection
        "test\r\nX-Injected: header",  # Header injection attempt
    ]

    for malformed_host in malformed_hosts:
        response = client.get("/", HTTP_HOST=malformed_host)
        assert response.status_code == 400, f"Malformed host '{malformed_host[:50]}...' should be rejected with 400"
        assert b"Invalid host header" in response.content


@pytest.mark.django_db
def test_middleware_handles_malformed_x_forwarded_host(client, settings):
    """
    Test that middleware gracefully handles malformed X-Forwarded-Host headers.

    When USE_X_FORWARDED_HOST=True, Django's request.get_host() uses the
    X-Forwarded-Host header value. Attackers may send malicious values
    attempting XSS or other attacks.

    The middleware should catch DisallowedHost exceptions and return 400.
    """
    # Ensure USE_X_FORWARDED_HOST is enabled (it should be by default)
    assert settings.USE_X_FORWARDED_HOST is True

    # XSS attack payload from the real Sentry error
    xss_payload = 'is6x5g.xfh"></script><script>alert(document.domain);</script>'

    # Make request with malicious X-Forwarded-Host header
    # Note: HTTP_X_FORWARDED_HOST is how Django test client sets the header
    response = client.get(
        "/",
        HTTP_HOST="localhost",  # Valid Host header
        HTTP_X_FORWARDED_HOST=xss_payload,  # Malicious forwarded host
    )

    # Should get 400, not 500 (no exception should propagate)
    assert response.status_code == 400, f"Expected 400 for malformed X-Forwarded-Host, got {response.status_code}"
    assert b"Invalid host header" in response.content
