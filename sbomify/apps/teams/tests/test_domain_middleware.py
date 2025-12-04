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
