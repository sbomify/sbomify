"""Tests for workspace settings tab persistence."""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
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
    assert response.url.endswith("#members")


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
            "max_users": 10,
            "max_products": 100,
            "max_projects": 100,
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
    assert response.url.endswith("#members")


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
            "max_users": 10,
            "max_products": 100,
            "max_projects": 100,
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
    assert response.url.endswith("#members")
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
        """Valid tab names should be included in the redirect URL."""
        team_key = sample_team_with_owner_member.team.key
        for tab in ALLOWED_TABS:
            response = redirect_to_team_settings(team_key, tab)
            assert response.url.endswith(f"#{tab}")

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

