import pytest

from sbomify.apps.compliance.permissions import check_cra_access

pytestmark = pytest.mark.django_db


class TestCRABillingGate:
    def test_community_plan_blocked(self, team_with_community_plan):
        assert check_cra_access(team_with_community_plan) is False

    def test_business_plan_allowed(self, team_with_business_plan):
        assert check_cra_access(team_with_business_plan) is True

    def test_billing_disabled_allowed(self, sample_team, settings):
        settings.BILLING = False
        assert check_cra_access(sample_team) is True

    def test_no_plan_blocked(self, sample_team):
        """Team with no billing plan should be blocked."""
        sample_team.billing_plan = "nonexistent"
        sample_team.save()
        assert check_cra_access(sample_team) is False
