"""Tests for user limits and NTIA feature gating functionality."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.utils import can_add_user_to_team

User = get_user_model()


class UserLimitsTestCase(TestCase):
    """Test user limits for different billing plans."""

    def setUp(self):
        """Set up test data."""
        self.user1 = User.objects.create_user(username="user1", email="user1@example.com", password="test")
        self.user2 = User.objects.create_user(username="user2", email="user2@example.com", password="test")
        self.user3 = User.objects.create_user(username="user3", email="user3@example.com", password="test")

        # Create billing plans
        self.community_plan = BillingPlan.objects.create(
            key="community",
            name="Community",
            max_users=1
        )

        self.business_plan = BillingPlan.objects.create(
            key="business",
            name="Business",
            max_users=5
        )

        self.enterprise_plan = BillingPlan.objects.create(
            key="enterprise",
            name="Enterprise",
            max_users=None  # Unlimited
        )

    def test_community_plan_user_limit(self):
        """Test that community plan allows only 1 user."""
        team = Team.objects.create(name="Community Team", billing_plan="community")
        Member.objects.create(user=self.user1, team=team, role="owner")

        # Should not be able to add another user
        can_add, message = can_add_user_to_team(team)
        self.assertFalse(can_add)
        self.assertIn("Community plan allows only 1 user", message)

    def test_business_plan_user_limit(self):
        """Test that business plan allows up to 5 users."""
        team = Team.objects.create(name="Business Team", billing_plan="business")
        Member.objects.create(user=self.user1, team=team, role="owner")

        # Should be able to add up to 4 more users
        can_add, message = can_add_user_to_team(team)
        self.assertTrue(can_add)
        self.assertEqual(message, "")

        # Add 4 more members to reach the limit
        for i in range(4):
            user = User.objects.create_user(username=f"user{i+10}", email=f"user{i+10}@example.com", password="test")
            Member.objects.create(user=user, team=team, role="member")

        # Should not be able to add another user
        can_add, message = can_add_user_to_team(team)
        self.assertFalse(can_add)
        self.assertIn("allows only 5 users", message)

    def test_enterprise_plan_unlimited_users(self):
        """Test that enterprise plan allows unlimited users."""
        team = Team.objects.create(name="Enterprise Team", billing_plan="enterprise")
        Member.objects.create(user=self.user1, team=team, role="owner")

        # Should be able to add users without limit
        can_add, message = can_add_user_to_team(team)
        self.assertTrue(can_add)
        self.assertEqual(message, "")

        # Add many members and should still be able to add more
        for i in range(10):
            user = User.objects.create_user(username=f"user{i+20}", email=f"user{i+20}@example.com", password="test")
            Member.objects.create(user=user, team=team, role="member")

        can_add, message = can_add_user_to_team(team)
        self.assertTrue(can_add)
        self.assertEqual(message, "")

    def test_no_billing_plan_defaults_to_community(self):
        """Test that teams without billing plan default to community limits."""
        team = Team.objects.create(name="No Plan Team")  # No billing_plan set
        Member.objects.create(user=self.user1, team=team, role="owner")

        # Should not be able to add another user (defaults to community)
        can_add, message = can_add_user_to_team(team)
        self.assertFalse(can_add)
        self.assertIn("Community plan allows only 1 user", message)

    def test_invalid_billing_plan_defaults_to_community(self):
        """Test that teams with invalid billing plan default to community limits."""
        team = Team.objects.create(name="Invalid Plan Team", billing_plan="invalid_plan")
        Member.objects.create(user=self.user1, team=team, role="owner")

        # Should not be able to add another user (defaults to community)
        can_add, message = can_add_user_to_team(team)
        self.assertFalse(can_add)
        self.assertIn("Community plan allows only 1 user", message)

    def test_community_team_with_multiple_users_grandfathered(self):
        """Test that existing community teams with multiple users can't add more but aren't broken."""
        # Create a community team with multiple users (simulating legacy data)
        team = Team.objects.create(
            name="Legacy Community Team",
            billing_plan="community"
        )

        # Add multiple users (simulating pre-limit situation)
        owner = User.objects.create_user(username="legacy_owner", email="legacy_owner@test.com")
        user2 = User.objects.create_user(username="legacy_user2", email="legacy_user2@test.com")
        user3 = User.objects.create_user(username="legacy_user3", email="legacy_user3@test.com")

        Member.objects.create(team=team, user=owner, role="owner")
        Member.objects.create(team=team, user=user2, role="member")
        Member.objects.create(team=team, user=user3, role="member")

        # Verify current state: team has 3 users on community plan
        member_count = Member.objects.filter(team=team).count()
        self.assertEqual(member_count, 3)
        self.assertEqual(team.billing_plan, "community")

        # Verify they cannot add more users
        can_add, error_message = can_add_user_to_team(team)
        self.assertFalse(can_add)
        self.assertIn("Community plan allows only 1 user", error_message)
        self.assertIn("Please upgrade your plan to add more members", error_message)

        # Verify the existing users can still function normally
        # (This would test existing functionality like accessing team resources)
        # The team still works, just can't grow
        self.assertTrue(team.name == "Legacy Community Team")
        self.assertTrue(all(member.team == team for member in Member.objects.filter(team=team)))

    def test_business_team_with_excess_users_grandfathered(self):
        """Test that existing business teams with >5 users are grandfathered on business plan."""
        # Create a business team with more than 5 users (simulating legacy data)
        team = Team.objects.create(
            name="Legacy Business Team",
            billing_plan="business"
        )

        # Add 7 users (exceeding business plan limit of 5)
        for i in range(7):
            user = User.objects.create_user(username=f"legacy_biz_user{i}", email=f"legacy_biz_user{i}@test.com")
            Member.objects.create(team=team, user=user, role="owner" if i == 0 else "member")

        # Verify current state: team has 7 users on business plan
        member_count = Member.objects.filter(team=team).count()
        self.assertEqual(member_count, 7)
        self.assertEqual(team.billing_plan, "business")

        # Verify they cannot add more users
        can_add, error_message = can_add_user_to_team(team)
        self.assertFalse(can_add)
        self.assertIn("Business plan allows only 5 users", error_message)
        self.assertIn("Please upgrade your plan to add more members", error_message)

        # Verify the team remains on business plan (not auto-upgraded to enterprise)
        self.assertEqual(team.billing_plan, "business")
        self.assertTrue(all(member.team == team for member in Member.objects.filter(team=team)))


class NTIAFeatureGatingTestCase(TestCase):
    """Test NTIA feature gating for different billing plans."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="user", email="user@example.com", password="test")

        # Create billing plans
        self.community_plan = BillingPlan.objects.create(
            key="community",
            name="Community",
            max_users=1
        )

        self.business_plan = BillingPlan.objects.create(
            key="business",
            name="Business",
            max_users=5
        )

        self.enterprise_plan = BillingPlan.objects.create(
            key="enterprise",
            name="Enterprise",
            max_users=None
        )

    def test_billing_plan_has_ntia_compliance_property(self):
        """Test that billing plans have correct NTIA compliance properties."""
        self.assertFalse(self.community_plan.has_ntia_compliance)
        self.assertTrue(self.business_plan.has_ntia_compliance)
        self.assertTrue(self.enterprise_plan.has_ntia_compliance)

    def test_billing_plan_has_vulnerability_scanning_property(self):
        """Test that billing plans have correct vulnerability scanning properties."""
        # OSV vulnerability scanning is now available for all teams
        self.assertTrue(self.community_plan.has_vulnerability_scanning)
        self.assertTrue(self.business_plan.has_vulnerability_scanning)
        self.assertTrue(self.enterprise_plan.has_vulnerability_scanning)

        # But Dependency Track access is only for business/enterprise
        self.assertFalse(self.community_plan.has_dependency_track_access)
        self.assertTrue(self.business_plan.has_dependency_track_access)
        self.assertTrue(self.enterprise_plan.has_dependency_track_access)

    @patch("sbomify.apps.sboms.tasks.check_sbom_ntia_compliance.send_with_options")
    def test_ntia_compliance_not_triggered_for_community(self, mock_task):
        """Test that NTIA compliance is not triggered for community plans."""
        team = Team.objects.create(name="Community Team", billing_plan="community")
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should not trigger NTIA compliance check
        _sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # NTIA compliance task should not be called
        mock_task.assert_not_called()

    @patch("sbomify.apps.sboms.tasks.check_sbom_ntia_compliance.send_with_options")
    def test_ntia_compliance_triggered_for_business(self, mock_task):
        """Test that NTIA compliance is triggered for business plans."""
        team = Team.objects.create(name="Business Team", billing_plan="business")
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should trigger NTIA compliance check
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # NTIA compliance task should be called
        mock_task.assert_called_once_with(args=[sbom.id], delay=60000)

    @patch("sbomify.apps.sboms.tasks.check_sbom_ntia_compliance.send_with_options")
    def test_ntia_compliance_triggered_for_enterprise(self, mock_task):
        """Test that NTIA compliance is triggered for enterprise plans."""
        team = Team.objects.create(name="Enterprise Team", billing_plan="enterprise")
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should trigger NTIA compliance check
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # NTIA compliance task should be called
        mock_task.assert_called_once_with(args=[sbom.id], delay=60000)

    @patch("sbomify.apps.sboms.tasks.check_sbom_ntia_compliance.send_with_options")
    def test_ntia_compliance_not_triggered_for_no_plan(self, mock_task):
        """Test that NTIA compliance is not triggered when team has no billing plan."""
        team = Team.objects.create(name="No Plan Team")  # No billing_plan set
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should not trigger NTIA compliance check
        _sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # NTIA compliance task should not be called
        mock_task.assert_not_called()

    @patch("sbomify.apps.sboms.tasks.check_sbom_ntia_compliance.send_with_options")
    def test_ntia_compliance_not_triggered_for_invalid_plan(self, mock_task):
        """Test that NTIA compliance is not triggered for invalid billing plans."""
        team = Team.objects.create(name="Invalid Plan Team", billing_plan="invalid_plan")
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should not trigger NTIA compliance check
        _sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # NTIA compliance task should not be called
        mock_task.assert_not_called()

    @patch("sbomify.apps.vulnerability_scanning.tasks.scan_sbom_for_vulnerabilities_unified.send_with_options")
    def test_vulnerability_scan_triggered_for_community(self, mock_task):
        """Test that vulnerability scanning is triggered for community plans (using OSV)."""
        team = Team.objects.create(name="Community Team", billing_plan="community")
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should trigger vulnerability scan with OSV
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # Vulnerability scan task should be called
        mock_task.assert_called_once_with(args=[sbom.id], delay=90000)

    @patch("sbomify.apps.vulnerability_scanning.tasks.scan_sbom_for_vulnerabilities_unified.send_with_options")
    def test_vulnerability_scan_triggered_for_business(self, mock_task):
        """Test that vulnerability scanning is triggered for business plans."""
        team = Team.objects.create(name="Business Team", billing_plan="business")
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should trigger vulnerability scan
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # Vulnerability scan task should be called
        mock_task.assert_called_once_with(args=[sbom.id], delay=90000)

    @patch("sbomify.apps.vulnerability_scanning.tasks.scan_sbom_for_vulnerabilities_unified.send_with_options")
    def test_vulnerability_scan_triggered_for_enterprise(self, mock_task):
        """Test that vulnerability scanning is triggered for enterprise plans."""
        team = Team.objects.create(name="Enterprise Team", billing_plan="enterprise")
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should trigger vulnerability scan
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # Vulnerability scan task should be called
        mock_task.assert_called_once_with(args=[sbom.id], delay=90000)

    @patch("sbomify.apps.vulnerability_scanning.tasks.scan_sbom_for_vulnerabilities_unified.send_with_options")
    def test_vulnerability_scan_triggered_for_no_plan(self, mock_task):
        """Test that vulnerability scanning is triggered when team has no billing plan (using OSV)."""
        team = Team.objects.create(name="No Plan Team")  # No billing_plan set
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should trigger vulnerability scan with OSV
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # Vulnerability scan task should be called
        mock_task.assert_called_once_with(args=[sbom.id], delay=90000)

    @patch("sbomify.apps.vulnerability_scanning.tasks.scan_sbom_for_vulnerabilities_unified.send_with_options")
    def test_vulnerability_scan_triggered_for_invalid_plan(self, mock_task):
        """Test that vulnerability scanning is triggered for invalid billing plans (using OSV)."""
        team = Team.objects.create(name="Invalid Plan Team", billing_plan="invalid_plan")
        Member.objects.create(user=self.user, team=team, role="owner")
        component = Component.objects.create(name="Test Component", team=team)

        # Create SBOM - this should trigger vulnerability scan with OSV
        sbom = SBOM.objects.create(
            name="test-sbom",
            component=component,
            format="spdx"
        )

        # Vulnerability scan task should be called
        mock_task.assert_called_once_with(args=[sbom.id], delay=90000)


class InvitationUserLimitsTestCase(TestCase):
    """Test user limits in invitation flows."""

    def setUp(self):
        """Set up test data."""
        self.user1 = User.objects.create_user(username="owner", email="owner@example.com", password="test")
        self.user2 = User.objects.create_user(username="invitee", email="invitee@example.com", password="test")

        # Create community plan with 1 user limit
        self.community_plan = BillingPlan.objects.create(
            key="community",
            name="Community",
            max_users=1
        )

    def test_invitation_creation_respects_user_limits(self):
        """Test that invitations cannot be created when user limit is reached."""
        team = Team.objects.create(name="Community Team", billing_plan="community")
        Member.objects.create(user=self.user1, team=team, role="owner")

        # Should not be able to create invitation
        can_add, message = can_add_user_to_team(team)
        self.assertFalse(can_add)
        self.assertIn("Community plan allows only 1 user", message)

    def test_invitation_acceptance_respects_user_limits(self):
        """Test that invitations cannot be accepted when user limit is reached."""
        team = Team.objects.create(name="Community Team", billing_plan="community")
        Member.objects.create(user=self.user1, team=team, role="owner")

        # Create invitation (bypassing the normal flow for testing)
        _invitation = Invitation.objects.create(
            team=team,
            email=self.user2.email,
            role="member"
        )

        # Should not be able to accept invitation due to user limits
        can_add, message = can_add_user_to_team(team)
        self.assertFalse(can_add)
        self.assertIn("Community plan allows only 1 user", message)