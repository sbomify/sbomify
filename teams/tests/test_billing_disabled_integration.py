"""Integration tests for team creation when billing is disabled."""
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from billing.models import BillingPlan
from teams.models import Team, Member

User = get_user_model()

# Import billing fixtures
pytest_plugins = ["billing.tests.fixtures"]


@pytest.mark.django_db
class TestBillingDisabledIntegration:
    """Integration tests for team creation behavior when billing is disabled."""

    @override_settings(BILLING=False)
    def test_team_with_enterprise_plan_has_unlimited_limits(self, team_with_enterprise_plan):
        """Test that enterprise teams have unlimited limits when billing is disabled."""
        team = team_with_enterprise_plan

        # Check if team has enterprise plan with unlimited limits
        assert team.billing_plan == "enterprise"
        assert team.billing_plan_limits["subscription_status"] == "active"
        # Enterprise plan should have unlimited limits
        assert team.billing_plan_limits["max_products"] is None
        assert team.billing_plan_limits["max_projects"] is None
        assert team.billing_plan_limits["max_components"] is None

    @override_settings(BILLING=False)
    def test_team_with_community_plan_gets_enterprise_limits_when_billing_disabled(self, team_with_community_plan):
        """Test that community teams get enterprise-like behavior when billing is disabled."""
        team = team_with_community_plan

        # Even though the team has community plan, billing limits should be bypassed when billing=false
        assert team.billing_plan == "community"
        # The billing processing should bypass limits when BILLING=False
        from billing.billing_processing import get_current_limits
        limits = get_current_limits(team)
        assert limits["max_products"] is None
        assert limits["max_projects"] is None
        assert limits["max_components"] is None

    @override_settings(BILLING=True)
    def test_team_with_business_plan_has_limited_resources(self, team_with_business_plan):
        """Test that business teams have limited resources when billing is enabled."""
        team = team_with_business_plan

        # Check if team has business plan with limited resources
        assert team.billing_plan == "business"
        assert team.billing_plan_limits["subscription_status"] == "active"
        assert team.billing_plan_limits["max_products"] == 10
        assert team.billing_plan_limits["max_projects"] == 20
        assert team.billing_plan_limits["max_components"] == 100
