"""Tests for custom domain UI in workspace branding settings."""

import pytest
from django.test import Client, override_settings

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.views.team_branding import check_custom_domain_access, get_app_hostname


class TestGetAppHostname:
    """Tests for get_app_hostname helper function."""

    @override_settings(APP_BASE_URL="https://app.sbomify.io")
    def test_extracts_hostname_from_full_url(self):
        """Should extract hostname from full URL with protocol."""
        assert get_app_hostname() == "app.sbomify.io"

    @override_settings(APP_BASE_URL="http://localhost:8000")
    def test_extracts_hostname_from_localhost(self):
        """Should handle localhost URLs."""
        assert get_app_hostname() == "localhost"

    @override_settings(APP_BASE_URL="app.sbomify.io")
    def test_extracts_hostname_without_protocol(self):
        """Should handle URLs without protocol."""
        assert get_app_hostname() == "app.sbomify.io"

    @override_settings(APP_BASE_URL="")
    def test_returns_empty_string_for_empty_url(self):
        """Should return empty string if APP_BASE_URL is empty."""
        assert get_app_hostname() == ""

    @override_settings(APP_BASE_URL="https://app.example.com:443/path")
    def test_extracts_hostname_ignoring_port_and_path(self):
        """Should extract only hostname, ignoring port and path."""
        assert get_app_hostname() == "app.example.com"


@pytest.mark.django_db
class TestCheckCustomDomainAccess:
    """Tests for check_custom_domain_access helper function."""

    def test_business_plan_has_access(self):
        """Business plan should have custom domain access."""
        assert check_custom_domain_access("business") is True

    def test_enterprise_plan_has_access(self):
        """Enterprise plan should have custom domain access."""
        assert check_custom_domain_access("enterprise") is True

    def test_community_plan_no_access(self):
        """Community plan should not have custom domain access."""
        assert check_custom_domain_access("community") is False

    def test_free_plan_no_access(self):
        """Free plan should not have custom domain access."""
        assert check_custom_domain_access("free") is False

    def test_empty_plan_no_access(self):
        """Empty/None plan should not have custom domain access."""
        assert check_custom_domain_access("") is False
        assert check_custom_domain_access(None) is False

    def test_case_insensitive(self):
        """Plan check should be case insensitive."""
        assert check_custom_domain_access("BUSINESS") is True
        assert check_custom_domain_access("Business") is True
        assert check_custom_domain_access("ENTERPRISE") is True

    def test_whitespace_stripped(self):
        """Plan check should strip whitespace."""
        assert check_custom_domain_access("  business  ") is True

    def test_billing_plan_model_lookup(self):
        """Should look up BillingPlan model if it exists."""
        # Create a custom billing plan with domain access
        BillingPlan.objects.create(
            key="custom_paid",
            name="Custom Paid Plan",
        )
        # Since has_custom_domain_access is a property that checks key in ["business", "enterprise"]
        # custom plans that aren't in that list should fall back to False
        assert check_custom_domain_access("custom_paid") is False


@pytest.mark.django_db
class TestTeamBrandingViewCustomDomain:
    """Tests for custom domain context in TeamBrandingView."""

    @pytest.fixture
    def business_team(self, sample_user):
        """Create a team with business plan."""
        team = Team.objects.create(name="Business Team", billing_plan="business")
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)
        return team

    @pytest.fixture
    def community_team(self, sample_user):
        """Create a team with community plan."""
        team = Team.objects.create(name="Community Team", billing_plan="community")
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)
        return team

    @pytest.fixture
    def team_with_domain(self, sample_user):
        """Create a team with a configured custom domain."""
        team = Team.objects.create(
            name="Domain Team",
            billing_plan="business",
            custom_domain="sbom.example.com",
            custom_domain_validated=True,
        )
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)
        return team

    @override_settings(APP_BASE_URL="https://app.sbomify.io")
    def test_business_team_sees_custom_domain_section(self, business_team, sample_user):
        """Business plan team should see the custom domain section."""
        client = Client()
        setup_authenticated_client_session(client, business_team, sample_user)

        response = client.get(f"/workspaces/{business_team.key}/branding")
        assert response.status_code == 200

        content = response.content.decode()
        assert "Custom Domain" in content
        assert "app.sbomify.io" in content
        # Check that the upgrade badge is NOT shown (hasAccess should be true)
        assert 'hasAccess: true' in content

    @override_settings(APP_BASE_URL="https://app.sbomify.io")
    def test_community_team_sees_upgrade_prompt(self, community_team, sample_user):
        """Community plan team should see upgrade prompt instead of domain config."""
        client = Client()
        setup_authenticated_client_session(client, community_team, sample_user)

        response = client.get(f"/workspaces/{community_team.key}/branding")
        assert response.status_code == 200

        content = response.content.decode()
        assert "Custom Domain" in content
        assert "Business / Enterprise" in content  # Badge should show
        assert "available on" in content.lower()

    @override_settings(APP_BASE_URL="https://app.sbomify.io")
    def test_team_with_domain_shows_verification_status(self, team_with_domain, sample_user):
        """Team with configured domain should show verification status."""
        client = Client()
        setup_authenticated_client_session(client, team_with_domain, sample_user)

        response = client.get(f"/workspaces/{team_with_domain.key}/branding")
        assert response.status_code == 200

        content = response.content.decode()
        assert "sbom.example.com" in content
        # Since the domain is validated, isValidated should be true in the JS config
        assert "isValidated: true" in content

    @override_settings(APP_BASE_URL="https://app.sbomify.io")
    def test_pending_verification_status(self, sample_user):
        """Team with unverified domain should show pending status."""
        team = Team.objects.create(
            name="Pending Team",
            billing_plan="business",
            custom_domain="pending.example.com",
            custom_domain_validated=False,
        )
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)

        client = Client()
        setup_authenticated_client_session(client, team, sample_user)

        response = client.get(f"/workspaces/{team.key}/branding")
        assert response.status_code == 200

        content = response.content.decode()
        assert "pending.example.com" in content
        assert "isValidated: false" in content

    @override_settings(APP_BASE_URL="https://app.sbomify.io")
    def test_no_domain_shows_empty_state(self, business_team, sample_user):
        """Team without domain should show empty domain field."""
        client = Client()
        setup_authenticated_client_session(client, business_team, sample_user)

        response = client.get(f"/workspaces/{business_team.key}/branding")
        assert response.status_code == 200

        content = response.content.decode()
        # Initial domain should be empty
        assert "initialDomain: ''" in content
        # Should show DNS configuration instructions
        assert "CNAME" in content

