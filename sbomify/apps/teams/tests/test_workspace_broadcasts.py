"""Membership, invitation and custom domain changes tell the workspace.

The members tab repaints on ``member_updated`` and ``invitation_updated``, and
a removed member's open socket closes on its own ``member_updated``. The
custom domain card repaints on ``custom_domain_updated``. Every member who may
read the workspace hears these, so they carry ids, an action or a status, and
never an email address or a domain.

Membership and invitation messages come from model signals, because there are
more ways in and out of a workspace than any one list of views: the invite
link, the settings page, sign-in auto-accept, the API and the trust center all
create or delete these rows.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Invitation, Member, Workspace

BROADCAST = "sbomify.apps.teams.broadcasts.broadcast_to_workspace"

pytestmark = pytest.mark.django_db


def _sent(mock_broadcast: Any, message_type: str | None = None, workspace_key: str | None = None) -> list[dict]:
    return [
        call.kwargs["data"]
        for call in mock_broadcast.call_args_list
        if (message_type is None or call.kwargs["message_type"] == message_type)
        and (workspace_key is None or call.kwargs["workspace_key"] == workspace_key)
    ]


@pytest.fixture
def team(ensure_billing_plans: Any) -> Workspace:
    return Workspace.objects.create(name="Broadcast Workspace", billing_plan="business")


@pytest.fixture
def make_user(django_user_model: Any) -> Any:
    def make(username: str) -> Any:
        return django_user_model.objects.create_user(
            username=username, email=f"{username}@example.com", password="pw", email_verified=True
        )

    return make


@pytest.fixture
def owner(team: Workspace, make_user: Any) -> Any:
    user = make_user("bc-owner")
    Member.objects.create(team=team, user=user, role="owner", is_default_team=True)
    return user


@pytest.fixture
def owner_client(team: Workspace, owner: Any) -> Client:
    client = Client()
    setup_authenticated_client_session(client, team, owner)
    return client


@pytest.fixture
def member(team: Workspace, make_user: Any) -> Member:
    return Member.objects.create(team=team, user=make_user("bc-member"), role="member")


def _api_client(user: Any) -> Client:
    encoded = create_personal_access_token(user)
    AccessToken.objects.create(user=user, encoded_token=encoded, description="broadcasts")
    return Client(HTTP_AUTHORIZATION=f"Bearer {encoded}")


class TestMembers:
    def test_removing_on_the_settings_page(
        self, team: Workspace, owner_client: Client, member: Member, django_capture_on_commit_callbacks: Any
    ) -> None:
        url = reverse("workspaces:team_settings", kwargs={"workspace_key": team.key})

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            response = owner_client.post(url, {"_method": "DELETE", "member_id": member.pk, "active_tab": "members"})

        assert response.status_code == 302
        # Their last workspace, so they are also given a personal one of their
        # own; that one announces itself to its own (empty) workspace.
        assert _sent(mock_broadcast, workspace_key=team.key) == [{"user_id": str(member.user_id), "action": "removed"}]

    def test_removing_through_the_bare_member_url(
        self, team: Workspace, owner_client: Client, member: Member, django_capture_on_commit_callbacks: Any
    ) -> None:
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            response = owner_client.post(
                reverse("workspaces:team_membership_delete", kwargs={"membership_id": member.pk})
            )

        assert response.status_code == 302
        assert _sent(mock_broadcast, workspace_key=team.key) == [{"user_id": str(member.user_id), "action": "removed"}]

    def test_a_refused_removal_broadcasts_nothing(
        self, team: Workspace, owner: Any, member: Member, django_capture_on_commit_callbacks: Any
    ) -> None:
        client = Client()
        setup_authenticated_client_session(client, team, member.user)
        owner_membership = Member.objects.get(team=team, user=owner)

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("workspaces:team_membership_delete", kwargs={"membership_id": owner_membership.pk}))

        assert Member.objects.filter(pk=owner_membership.pk).exists()
        mock_broadcast.assert_not_called()

    def test_a_role_change(self, team: Workspace, member: Member, django_capture_on_commit_callbacks: Any) -> None:
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            member.role = "admin"
            member.save(update_fields=["role"])

        assert _sent(mock_broadcast) == [{"user_id": str(member.user_id), "action": "role_changed"}]

    def test_a_save_that_keeps_the_role_says_nothing(
        self, member: Member, django_capture_on_commit_callbacks: Any
    ) -> None:
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            member.is_default_team = True
            member.save()

        mock_broadcast.assert_not_called()

    def test_nothing_is_sent_when_the_change_rolls_back(
        self, member: Member, django_capture_on_commit_callbacks: Any
    ) -> None:
        from django.db import transaction

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                member.delete()
                transaction.set_rollback(True)

        mock_broadcast.assert_not_called()


class TestInvitations:
    def test_inviting_on_the_members_page(
        self, team: Workspace, owner_client: Client, django_capture_on_commit_callbacks: Any
    ) -> None:
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            response = owner_client.post(
                reverse("workspaces:invite_user", kwargs={"workspace_key": team.key}),
                {"email": "new.dev@example.com", "role": "member"},
            )

        assert response.status_code == 302
        invitation = Invitation.objects.get(team=team, email="new.dev@example.com")
        mock_broadcast.assert_called_once_with(
            workspace_key=team.key,
            message_type="invitation_updated",
            data={"invitation_id": str(invitation.pk), "action": "created"},
        )

    def test_inviting_and_revoking_over_the_api(
        self, team: Workspace, owner: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        client = _api_client(owner)
        url = f"/api/v1/workspaces/{team.key}/invitations"

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            created = client.post(
                url, {"email": "api.dev@example.com", "role": "member"}, content_type="application/json"
            )
            invitation_id = created.json()["id"]
            revoked = client.delete(f"{url}/{invitation_id}")

        assert (created.status_code, revoked.status_code) == (201, 204)
        assert _sent(mock_broadcast) == [
            {"invitation_id": str(invitation_id), "action": "created"},
            {"invitation_id": str(invitation_id), "action": "revoked"},
        ]

    def test_revoking_on_the_settings_page(
        self, team: Workspace, owner: Any, owner_client: Client, django_capture_on_commit_callbacks: Any
    ) -> None:
        invitation = Invitation.objects.create(team=team, email="gone@example.com", role="member", invited_by=owner)
        url = reverse("workspaces:team_settings", kwargs={"workspace_key": team.key})

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            owner_client.post(url, {"_method": "DELETE", "invitation_id": invitation.pk, "active_tab": "members"})

        assert _sent(mock_broadcast) == [{"invitation_id": str(invitation.pk), "action": "revoked"}]

    def test_accepting_the_emailed_link(
        self, team: Workspace, make_user: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        invitee = make_user("bc-invitee")
        home = Workspace.objects.create(name="Invitee Home")
        Member.objects.create(team=home, user=invitee, role="owner", is_default_team=True)
        invitation = Invitation.objects.create(team=team, email=invitee.email, role="member")
        client = Client()
        client.force_login(invitee)

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            response = client.post(reverse("workspaces:accept_invite", kwargs={"invite_token": str(invitation.token)}))

        assert response.status_code == 302
        assert Member.objects.filter(team=team, user=invitee).exists()
        assert _sent(mock_broadcast, "member_updated") == [{"user_id": str(invitee.pk), "action": "added"}]
        assert _sent(mock_broadcast, "invitation_updated") == [
            {"invitation_id": str(invitation.pk), "action": "accepted"}
        ]
        for call in mock_broadcast.call_args_list:
            assert call.kwargs["workspace_key"] == team.key

    def test_accepting_from_the_settings_page(
        self, team: Workspace, make_user: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        """This path lives in core, outside this app; the signals still see it."""
        invitee = make_user("bc-settings-invitee")
        home = Workspace.objects.create(name="Settings Invitee Home")
        Member.objects.create(team=home, user=invitee, role="owner", is_default_team=True)
        invitation = Invitation.objects.create(team=team, email=invitee.email, role="admin")
        client = Client()
        client.force_login(invitee)

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("core:accept_user_invitation", kwargs={"invitation_id": invitation.pk}))

        assert _sent(mock_broadcast, "member_updated") == [{"user_id": str(invitee.pk), "action": "added"}]
        assert _sent(mock_broadcast, "invitation_updated") == [
            {"invitation_id": str(invitation.pk), "action": "accepted"}
        ]

    def test_an_invitation_to_an_existing_member_reports_the_role_change(
        self, team: Workspace, member: Member, django_capture_on_commit_callbacks: Any
    ) -> None:
        invitation = Invitation.objects.create(team=team, email=member.user.email, role="admin")
        client = Client()
        client.force_login(member.user)

        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("workspaces:accept_invite", kwargs={"invite_token": str(invitation.token)}))

        assert _sent(mock_broadcast, "member_updated") == [{"user_id": str(member.user_id), "action": "role_changed"}]
        assert _sent(mock_broadcast, "invitation_updated") == [
            {"invitation_id": str(invitation.pk), "action": "accepted"}
        ]

    def test_no_email_address_is_broadcast(
        self, team: Workspace, owner: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
            invitation = Invitation.objects.create(team=team, email="private@example.com", role="member")
            invitation.delete()

        assert mock_broadcast.call_count == 2
        assert "private@example.com" not in repr(mock_broadcast.call_args_list)


class TestMembersTabRefresh:
    def test_the_tab_listens_for_membership_messages(self, team: Workspace, owner_client: Client) -> None:
        url = reverse("workspaces:team_settings_tab", kwargs={"workspace_key": team.key, "tab": "members"})

        html = owner_client.get(url).content.decode()

        assert 'id="members-panel"' in html
        assert "'member_updated', 'invitation_updated', 'resync'" in html
        assert 'hx-trigger="refresh-members from:body"' in html

    def test_the_panel_refresh_renders_only_the_tab(
        self, team: Workspace, owner_client: Client, member: Member
    ) -> None:
        url = reverse("workspaces:team_settings_tab", kwargs={"workspace_key": team.key, "tab": "members"})

        response = owner_client.get(url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="members-panel")

        assert response.status_code == 200
        html = response.content.decode()
        assert 'id="members-panel"' in html
        assert member.user.email in html
        assert 'id="settings-content"' not in html

    def test_another_tabs_panel_name_gets_the_whole_page(self, team: Workspace, owner_client: Client) -> None:
        url = reverse("workspaces:team_settings_tab", kwargs={"workspace_key": team.key, "tab": "members"})

        response = owner_client.get(url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="integrations-panel")

        assert 'id="settings-content"' in response.content.decode()


class TestCustomDomain:
    DOMAIN = "trust.broadcast.example"

    @pytest.fixture
    def claimed(self, team: Workspace) -> Workspace:
        Workspace.objects.filter(pk=team.pk).update(custom_domain=self.DOMAIN)
        team.refresh_from_db()
        return team

    @pytest.mark.parametrize(("serves", "status"), [(True, "verified"), (False, "failed")])
    def test_a_probe_result_is_announced(
        self, serves: bool, status: str, claimed: Workspace, django_capture_on_commit_callbacks: Any
    ) -> None:
        from sbomify.apps.teams import tasks

        with (
            patch.object(tasks, "_serves_challenge", return_value=serves),
            patch(BROADCAST) as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            tasks.probe_custom_domain(claimed.pk, self.DOMAIN)

        mock_broadcast.assert_called_once_with(
            workspace_key=claimed.key, message_type="custom_domain_updated", data={"status": status}
        )

    def test_a_domain_changed_mid_probe_is_not_announced_as_verified(
        self, claimed: Workspace, django_capture_on_commit_callbacks: Any
    ) -> None:
        from sbomify.apps.teams import tasks

        with (
            patch.object(tasks, "_serves_challenge", return_value=True),
            patch(BROADCAST) as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            tasks.probe_custom_domain(claimed.pk, "old.broadcast.example")

        mock_broadcast.assert_not_called()

    def test_the_trust_center_tab_listens(self, team: Workspace, owner_client: Client) -> None:
        Workspace.objects.filter(pk=team.pk).update(is_public=True)
        url = reverse("workspaces:team_settings_tab", kwargs={"workspace_key": team.key, "tab": "trust-center"})

        html = owner_client.get(url).content.decode()

        assert "liveRegion({ refresh: ['custom_domain_updated']" in html
        assert "'access_request_updated', 'resync'" in html
