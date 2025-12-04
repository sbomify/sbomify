from urllib.parse import urlparse

import pytest


@pytest.mark.django_db
def test_dynamic_allowed_hosts():
    """Test that the dynamic ALLOWED_HOSTS logic works."""
    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Team
    from sbomify.settings import DynamicAllowedHosts

    # Setup allowed hosts list
    allowed_hosts = DynamicAllowedHosts(["localhost", "sbomify.com"])

    # 1. Test static hosts - parse hostname and ensure exact matching for bare host
    assert urlparse("http://localhost").hostname in allowed_hosts
    assert urlparse("http://sbomify.com").hostname in allowed_hosts
    assert "google.com" not in allowed_hosts

    # 2. Test custom domain (not yet in DB)
    custom_domain = "app.custom-customer.com"
    assert custom_domain not in allowed_hosts

    # 3. Add to DB
    team = Team.objects.create(name="Host Test Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = custom_domain
    team.save()

    # Clear cache after adding domain
    from django.core.cache import cache

    cache.delete(f"custom_domain:{custom_domain}")

    # 4. Should now be allowed
    assert custom_domain in allowed_hosts

    # 5. Check with port - parse to extract hostname
    custom_domain_with_port = f"{custom_domain}:8000"
    custom_domain_hostname = urlparse(f"http://{custom_domain_with_port}").hostname
    assert custom_domain_hostname in allowed_hosts


@pytest.mark.django_db
def test_custom_domain_middleware_validation(client, sample_user):
    """Test that the middleware validates domains upon traffic."""
    from sbomify.apps.core.utils import number_to_random_token
    from sbomify.apps.teams.models import Team

    # Create team with unvalidated domain
    team = Team.objects.create(name="Middleware Test Team", billing_plan="business")
    team.key = number_to_random_token(team.pk)
    team.custom_domain = "validated.example.com"
    team.custom_domain_validated = False
    team.save()

    # Send request with matching Host header
    # We use a path that doesn't require auth to keep it simple, or handle 404/302
    _ = client.get("/health/", HTTP_HOST="validated.example.com")

    # Check DB - should be validated now
    team.refresh_from_db()
    assert team.custom_domain_validated is True
    assert team.custom_domain_last_checked_at is not None

    # Send request with unknown host
    # Django's ALLOWED_HOSTS check happens deep in the request processing
    # If we mock ALLOWED_HOSTS or if the test client bypasses it in a specific way...
    # The test client normally enforces ALLOWED_HOSTS if we don't override it.
    # However, since we patched settings in the test environment, let's see.
    # Note: In tests, ALLOWED_HOSTS might be ['testserver'] by default.
