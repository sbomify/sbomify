"""Tests for workspace settings tab persistence."""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.fixtures import (  # noqa: F401
    sample_team_with_guest_member,
    sample_team_with_owner_member,
)
from sbomify.apps.teams.models import Invitation, Member
from sbomify.apps.teams.utils import ALLOWED_TABS, redirect_to_team_settings

User = get_user_model()


@pytest.mark.django_db
def test_visibility_toggle_redirects_to_active_tab(sample_team_with_owner_member: Member):  # noqa: F811
    """When toggling visibility from a specific tab, should redirect back to that tab."""
    client = Client()
    team = sample_team_with_owner_member.team
    user = sample_team_with_owner_member.user

    setup_authenticated_client_session(client, team, user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(
        uri,
        {
            "visibility_action": "update",
            "is_public": ["true"],
            "active_tab": "members",
        },
    )

    assert response.status_code == 302
    assert response.url.endswith("/settings/members")


@pytest.mark.django_db
def test_delete_invitation_redirects_to_members_tab(sample_team_with_owner_member: Member):  # noqa: F811
    """When deleting an invitation, should redirect back to members tab."""
    from sbomify.apps.billing.models import BillingPlan

    client = Client()
    team = sample_team_with_owner_member.team
    user = sample_team_with_owner_member.user

    # Set up a billing plan that allows invitations
    billing_plan, _ = BillingPlan.objects.get_or_create(
        key="business",
        defaults={
            "name": "Business Plan",
            "description": "Business Plan Description",
            "max_users": 10,
            "max_products": 100,
            "max_components": 1000,
        },
    )
    team.billing_plan = billing_plan.key
    team.save()

    # Create a test invitation
    invitation = Invitation.objects.create(team=team, email="test@example.com", role="guest")

    setup_authenticated_client_session(client, team, user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(
        uri,
        {
            "_method": "DELETE",
            "invitation_id": invitation.id,
            "active_tab": "members",
        },
    )

    assert response.status_code == 302
    assert response.url.endswith("/settings/members")


@pytest.mark.django_db
def test_redirect_without_active_tab_has_no_hash(sample_team_with_owner_member: Member):  # noqa: F811
    """When no active_tab is provided, redirect should not have a hash."""
    client = Client()
    team = sample_team_with_owner_member.team
    user = sample_team_with_owner_member.user

    setup_authenticated_client_session(client, team, user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(
        uri,
        {
            "visibility_action": "update",
            "is_public": ["true"],
        },
    )

    assert response.status_code == 302
    assert "#" not in response.url


@pytest.mark.django_db
def test_delete_member_redirects_to_active_tab(sample_team_with_owner_member: Member):  # noqa: F811
    """When deleting a member with active_tab, should redirect back to that tab."""
    from sbomify.apps.billing.models import BillingPlan

    client = Client()
    team = sample_team_with_owner_member.team
    owner = sample_team_with_owner_member.user

    # Set up billing plan that allows multiple users
    billing_plan, _ = BillingPlan.objects.get_or_create(
        key="business",
        defaults={
            "name": "Business Plan",
            "description": "Business Plan Description",
            "max_users": 10,
            "max_products": 100,
            "max_components": 1000,
        },
    )
    team.billing_plan = billing_plan.key
    team.save()

    # Create a second member to delete
    other_user = User.objects.create_user(username="otheruser", email="other@example.com", password="testpass")
    other_membership = Member.objects.create(team=team, user=other_user, role="guest")

    setup_authenticated_client_session(client, team, owner)

    uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(
        uri,
        {
            "_method": "DELETE",
            "member_id": other_membership.id,
            "active_tab": "members",
        },
    )

    assert response.status_code == 302
    assert response.url.endswith("/settings/members")
    # Verify member was actually deleted
    assert not Member.objects.filter(pk=other_membership.id).exists()


@pytest.mark.django_db
def test_invalid_active_tab_is_ignored(sample_team_with_owner_member: Member):  # noqa: F811
    """When an invalid active_tab is provided, it should be ignored (no hash in URL)."""
    client = Client()
    team = sample_team_with_owner_member.team
    user = sample_team_with_owner_member.user

    setup_authenticated_client_session(client, team, user)

    uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(
        uri,
        {
            "visibility_action": "update",
            "is_public": ["true"],
            "active_tab": "../../evil",  # Malicious input
        },
    )

    assert response.status_code == 302
    # Invalid tabs should not appear in URL
    assert "#" not in response.url
    assert "evil" not in response.url


class TestRedirectToTeamSettingsHelper:
    """Unit tests for the redirect_to_team_settings helper function."""

    @pytest.mark.django_db
    def test_valid_tab_is_included(self, sample_team_with_owner_member: Member):  # noqa: F811
        """A valid tab is named in the redirect, as a page where one exists.

        Sections with a page of their own redirect straight to it. The two names
        still in ALLOWED_TABS that have no page (controls, integrations) keep the
        old fragment form, so links to them are not broken by the move.
        """
        from sbomify.apps.teams.settings_tabs import TABS_BY_KEY

        team_key = sample_team_with_owner_member.team.key
        for tab in ALLOWED_TABS:
            response = redirect_to_team_settings(team_key, tab)
            expected = f"/settings/{tab}" if tab in TABS_BY_KEY else f"#{tab}"
            assert response.url.endswith(expected), f"{tab} -> {response.url}"

    @pytest.mark.django_db
    def test_invalid_tab_is_rejected(self, sample_team_with_owner_member: Member):  # noqa: F811
        """Invalid tab names should not appear in the redirect URL."""
        team_key = sample_team_with_owner_member.team.key
        invalid_tabs = ["invalid", "../../etc/passwd", "<script>", "   ", "MEMBERS", "Members"]
        for tab in invalid_tabs:
            response = redirect_to_team_settings(team_key, tab)
            assert "#" not in response.url

    @pytest.mark.django_db
    def test_none_tab_has_no_hash(self, sample_team_with_owner_member: Member):  # noqa: F811
        """None tab should result in URL without hash."""
        team_key = sample_team_with_owner_member.team.key
        response = redirect_to_team_settings(team_key, None)
        assert "#" not in response.url

    @pytest.mark.django_db
    def test_empty_string_tab_has_no_hash(self, sample_team_with_owner_member: Member):  # noqa: F811
        """Empty string tab should result in URL without hash."""
        team_key = sample_team_with_owner_member.team.key
        response = redirect_to_team_settings(team_key, "")
        assert "#" not in response.url

    @pytest.mark.django_db
    def test_invalid_team_key_redirects_to_dashboard(self):
        """Invalid team_key that doesn't exist should redirect to teams dashboard."""
        invalid_keys = ["abc123", "short", "../../etc/passwd", "<script>", ""]
        for invalid_key in invalid_keys:
            response = redirect_to_team_settings(invalid_key, "members")
            # Should redirect to teams dashboard when team_key doesn't exist
            assert response.url == "/workspaces/"


@pytest.mark.django_db
class TestMembersRoleLegend:
    """The members tab explains what each role can do.

    Roles are otherwise invisible: a user sees a badge saying "Admin" with no way
    to find out what that grants. The legend renders authz.ROLE_DESCRIPTIONS, so
    this also pins that the two stay wired together.
    """

    def test_members_tab_renders_role_descriptions(self, sample_team_with_owner_member: Member):  # noqa: F811
        from sbomify.apps.core.authz import ROLE_DESCRIPTIONS

        client = Client()
        team = sample_team_with_owner_member.team
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        # Each settings section is its own page, so target the members tab
        # directly rather than relying on which tab happens to be the default.
        response = client.get(reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "members"}))

        assert response.status_code == 200
        content = response.content.decode()
        assert "What can each role do?" in content
        for _role, label, description in ROLE_DESCRIPTIONS:
            assert label in content
            # The first clause is enough to prove the description body rendered
            # without depending on exact punctuation/wrapping.
            assert description.split(".")[0] in content

    def test_legend_reflects_the_owner_admin_boundary(self):
        """The two owner-exclusive rules must be stated to users, not just enforced."""
        from sbomify.apps.core.authz import ROLE_ADMIN, ROLE_DESCRIPTIONS

        admin_description = next(d for role, _label, d in ROLE_DESCRIPTIONS if role == ROLE_ADMIN)
        assert "Cannot remove an owner or delete the workspace." in admin_description


@pytest.mark.django_db
class TestTrustCenterDescription:
    """Tests for trust center description settings."""

    def test_update_trust_center_description(self, sample_team_with_owner_member: Member):  # noqa: F811
        """Owner should be able to update trust center description."""
        client = Client()
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user

        setup_authenticated_client_session(client, team, user)

        uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
        response = client.post(
            uri,
            {
                "trust_center_description_action": "update",
                "trust_center_description": "Custom description for our trust center.",
                "active_tab": "trust-center",
            },
        )

        assert response.status_code == 302
        assert response.url.endswith("/settings/trust-center")

        # Verify description was saved
        team.refresh_from_db()
        assert team.branding_info.get("trust_center_description") == "Custom description for our trust center."

    def test_clear_trust_center_description(self, sample_team_with_owner_member: Member):  # noqa: F811
        """Owner should be able to clear trust center description."""
        client = Client()
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user

        # Set initial description
        team.branding_info = {"trust_center_description": "Initial description"}
        team.save()

        setup_authenticated_client_session(client, team, user)

        uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
        response = client.post(
            uri,
            {
                "trust_center_description_action": "update",
                "trust_center_description": "",
                "active_tab": "trust-center",
            },
        )

        assert response.status_code == 302

        # Verify description was cleared
        team.refresh_from_db()
        assert team.branding_info.get("trust_center_description") == ""

    def test_trust_center_description_max_length(self, sample_team_with_owner_member: Member):  # noqa: F811
        """Trust center description should be limited to 500 characters."""
        client = Client()
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user

        setup_authenticated_client_session(client, team, user)

        uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
        response = client.post(
            uri,
            {
                "trust_center_description_action": "update",
                "trust_center_description": "x" * 501,  # Over the limit
                "active_tab": "trust-center",
            },
        )

        assert response.status_code == 302

        # Verify description was NOT saved (too long)
        team.refresh_from_db()
        assert team.branding_info.get("trust_center_description", "") != "x" * 501

    def test_admin_can_update_description(self, sample_team_with_owner_member: Member):  # noqa: F811
        """Trust-center config is ADMINISTER, so admins may update the description."""
        client = Client()
        team = sample_team_with_owner_member.team

        admin_user = User.objects.create_user(username="adminuser", email="admin@example.com", password="testpass")
        Member.objects.create(team=team, user=admin_user, role="admin")

        setup_authenticated_client_session(client, team, admin_user)

        uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
        response = client.post(
            uri,
            {
                "trust_center_description_action": "update",
                "trust_center_description": "Saved by an admin",
                "active_tab": "trust-center",
            },
        )

        assert response.status_code == 302

        team.refresh_from_db()
        assert team.branding_info.get("trust_center_description", "") == "Saved by an admin"

    def test_guest_cannot_update_description(self, sample_team_with_guest_member: Member):  # noqa: F811
        """Guests hold no governance capability."""
        client = Client()
        team = sample_team_with_guest_member.team

        setup_authenticated_client_session(client, team, sample_team_with_guest_member.user)

        uri = reverse("teams:team_settings", kwargs={"team_key": team.key})
        response = client.post(
            uri,
            {
                "trust_center_description_action": "update",
                "trust_center_description": "Should not be saved",
                "active_tab": "trust-center",
            },
        )

        assert response.status_code == 403

        team.refresh_from_db()
        assert team.branding_info.get("trust_center_description", "") != "Should not be saved"

