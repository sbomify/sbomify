"""Choosing where each message goes, and what happens when Slack says no."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.integrations.exceptions import ProviderAuthError, ProviderUnavailable
from sbomify.apps.integrations.models import Integration, NotificationRoute
from sbomify.apps.integrations.providers.slack import SLACK, SlackChannelError
from sbomify.apps.integrations.services import connections, notifications
from sbomify.apps.integrations.services.messages import Message
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db

EVENT = NotificationRoute.Event.VEX_SUBMISSIONS


def _route(integration: Integration, event: str = EVENT, **kwargs) -> NotificationRoute:
    defaults = {"channel_id": "C001", "channel_name": "security"}
    return NotificationRoute.objects.create(integration=integration, event=event, **{**defaults, **kwargs})


class TestTheTokenIsNeverRefreshed:
    def test_a_bot_token_is_used_as_stored(self, connected_slack) -> None:
        """No expiry and no refresh token is what Slack issues, not a dead connection."""
        assert connected_slack.token_expires_at is None
        assert not connected_slack.refresh_token

        assert connections.access_token(connected_slack, SLACK) == "xoxb-live"
        connected_slack.refresh_from_db()
        assert connected_slack.status == Integration.Status.CONNECTED

    def test_a_missing_token_needs_reconnecting(self, connected_slack) -> None:
        connected_slack.access_token = ""

        with pytest.raises(ProviderAuthError):
            connections.access_token(connected_slack, SLACK)


class TestSetRoute:
    def test_routes_an_event_to_a_listed_channel(self, connected_slack, fake_slack) -> None:
        result = notifications.set_route(connected_slack.team, "slack", EVENT, "C002")

        assert result.ok
        route = NotificationRoute.objects.get(integration=connected_slack, event=EVENT)
        assert (route.channel_id, route.channel_name) == ("C002", "vex-review")

    def test_refuses_a_channel_the_connection_cannot_list(self, connected_slack, fake_slack) -> None:
        """A hand-edited form must not point a workspace's news at a channel id it typed."""
        result = notifications.set_route(connected_slack.team, "slack", EVENT, "C999")

        assert not result.ok
        assert not NotificationRoute.objects.exists()

    def test_an_empty_channel_turns_the_event_off(self, connected_slack, fake_slack) -> None:
        _route(connected_slack)

        assert notifications.set_route(connected_slack.team, "slack", EVENT, "").ok
        assert not NotificationRoute.objects.exists()

    def test_changing_the_channel_clears_the_old_channels_error(self, connected_slack, fake_slack) -> None:
        _route(connected_slack, last_error="Invite the sbomify app to that channel, then try again.")

        notifications.set_route(connected_slack.team, "slack", EVENT, "C002")

        assert NotificationRoute.objects.get().last_error == ""

    def test_keeping_the_channel_does_not_list_them_again(self, connected_slack, fake_slack) -> None:
        """Changing only the severity re-posts the channel; Slack need not be asked."""
        _route(connected_slack, NotificationRoute.Event.NEW_VULNERABILITIES)

        result = notifications.set_route(
            connected_slack.team, "slack", NotificationRoute.Event.NEW_VULNERABILITIES, "C001", "critical"
        )

        assert result.ok
        assert fake_slack.list_calls == 0
        assert NotificationRoute.objects.get().min_severity == "critical"

    def test_refuses_an_unknown_severity(self, connected_slack, fake_slack) -> None:
        result = notifications.set_route(
            connected_slack.team, "slack", NotificationRoute.Event.NEW_VULNERABILITIES, "C001", "apocalyptic"
        )

        assert not result.ok

    def test_refuses_an_unknown_event(self, connected_slack, fake_slack) -> None:
        assert not notifications.set_route(connected_slack.team, "slack", "everything", "C001").ok

    def test_refuses_a_compliance_provider(self, connected_vanta, fake_slack) -> None:
        assert notifications.set_route(connected_vanta.team, "vanta", EVENT, "C001").status_code == 404

    def test_refuses_a_revoked_connection(self, connected_slack, fake_slack) -> None:
        connected_slack.status = Integration.Status.REVOKED
        connected_slack.save()

        assert notifications.set_route(connected_slack.team, "slack", EVENT, "C001").status_code == 409


class TestRoutesPanel:
    def test_offers_every_event_with_off_first(self, connected_slack, fake_slack) -> None:
        panel = notifications.routes_panel(connected_slack)

        assert [event["key"] for event in panel["events"]] == [
            "vex_submissions",
            "daily_digest",
            "new_vulnerabilities",
        ]
        options = panel["events"][0]["channel_options"]
        assert options[0] == {"value": "", "label": "Off"}
        assert {"value": "C002", "label": "#vex-review (private)"} in options
        assert panel["channels_error"] == ""

    def test_a_routed_channel_the_list_lost_stays_selected_as_itself(self, connected_slack, fake_slack) -> None:
        """Otherwise the select would claim the event goes to whichever channel is first."""
        _route(connected_slack, channel_id="C404", channel_name="old-alerts")

        options = notifications.routes_panel(connected_slack)["events"][0]["channel_options"]

        assert options[1] == {"value": "C404", "label": "#old-alerts"}

    def test_channels_are_cached_between_renders(self, connected_slack, fake_slack) -> None:
        notifications.routes_panel(connected_slack)
        notifications.routes_panel(connected_slack)

        assert fake_slack.list_calls == 1

    def test_a_slack_outage_is_explained_rather_than_raised(self, connected_slack, fake_slack) -> None:
        fake_slack.fail_with = ProviderUnavailable("Slack is not answering.", service="slack")

        panel = notifications.routes_panel(connected_slack)

        assert panel["channels_error"] == "Slack is not answering."
        assert panel["has_channels"] is False

    def test_a_refused_token_marks_the_connection(self, connected_slack, fake_slack) -> None:
        fake_slack.fail_with = ProviderAuthError("Slack refused the stored credential.", service="slack")

        notifications.routes_panel(connected_slack)

        connected_slack.refresh_from_db()
        assert connected_slack.status == Integration.Status.REVOKED

    def test_a_revoked_connection_does_not_ask_slack(self, connected_slack, fake_slack) -> None:
        connected_slack.status = Integration.Status.REVOKED

        notifications.routes_panel(connected_slack)

        assert fake_slack.list_calls == 0


class TestDeliver:
    message = Message(text="hello", blocks=[{"type": "divider"}])

    def test_records_a_delivery(self, connected_slack, fake_slack) -> None:
        route = _route(connected_slack, last_error="old")

        assert notifications.deliver(route, self.message).ok

        assert fake_slack.posts == [{"channel": "C001", "text": "hello", "blocks": [{"type": "divider"}]}]
        route.refresh_from_db()
        assert route.last_delivered_at is not None
        assert route.last_error == ""

    def test_a_refused_channel_is_recorded_on_the_route_only(self, connected_slack, fake_slack) -> None:
        route = _route(connected_slack)
        fake_slack.fail_with = SlackChannelError("That channel is archived.", service="slack")

        assert not notifications.deliver(route, self.message).ok

        route.refresh_from_db()
        connected_slack.refresh_from_db()
        assert route.last_error == "That channel is archived."
        assert connected_slack.status == Integration.Status.CONNECTED

    def test_a_refused_token_needs_reconnecting(self, connected_slack, fake_slack) -> None:
        route = _route(connected_slack)
        fake_slack.fail_with = ProviderAuthError("Slack refused the stored credential.", service="slack")

        assert not notifications.deliver(route, self.message).ok

        connected_slack.refresh_from_db()
        assert connected_slack.status == Integration.Status.REVOKED

    def test_an_unreachable_slack_raises_for_a_retry(self, connected_slack, fake_slack) -> None:
        route = _route(connected_slack)
        fake_slack.fail_with = ProviderUnavailable("Slack is not answering.", service="slack")

        with pytest.raises(ProviderUnavailable):
            notifications.deliver(route, self.message)

    def test_a_reconnect_meanwhile_is_not_marked_revoked(self, connected_slack, fake_slack) -> None:
        """The refusal was about the credential the reconnect replaced."""
        from datetime import timedelta

        route = _route(connected_slack)
        Integration.objects.filter(pk=connected_slack.pk).update(
            connected_at=connected_slack.connected_at + timedelta(minutes=1)
        )
        fake_slack.fail_with = ProviderAuthError("Slack refused the stored credential.", service="slack")

        notifications.deliver(route, self.message)

        connected_slack.refresh_from_db()
        assert connected_slack.status == Integration.Status.CONNECTED


class TestSendTest:
    def test_posts_to_the_routed_channel(self, connected_slack, fake_slack) -> None:
        _route(connected_slack)

        result = notifications.send_test(connected_slack.team, "slack", EVENT)

        assert result.ok
        assert fake_slack.posts[0]["channel"] == "C001"
        assert "VEX approval queue" in fake_slack.posts[0]["text"]

    def test_needs_a_channel_first(self, connected_slack, fake_slack) -> None:
        assert not notifications.send_test(connected_slack.team, "slack", EVENT).ok


class TestActiveRoutes:
    def test_only_working_connections_count(self, connected_slack) -> None:
        _route(connected_slack)
        assert notifications.active_routes(connected_slack.team_id, EVENT).count() == 1

        connected_slack.status = Integration.Status.REVOKED
        connected_slack.save()
        assert notifications.active_routes(connected_slack.team_id, EVENT).count() == 0


@pytest.mark.usefixtures("slack_credentials", "vanta_credentials")
class TestTheSettingsTab:
    def _panel(self, client, team):
        return client.get(reverse("integrations:panel", kwargs={"workspace_key": team.key}), HTTP_HX_REQUEST="true")

    def test_an_unconnected_slack_offers_to_connect(self, admin_client_for_team, sample_team_with_owner_member):
        response = self._panel(admin_client_for_team, sample_team_with_owner_member.team)

        assert response.status_code == 200
        assert b"Connect Slack" in response.content
        assert b"Once connected, sbomify can:" in response.content

    def test_a_connected_slack_lists_its_messages_and_no_sync(
        self, admin_client_for_team, connected_slack, fake_slack
    ) -> None:
        _route(connected_slack)

        response = self._panel(admin_client_for_team, connected_slack.team)
        content = response.content.decode()

        assert "Example Slack" in content
        assert "VEX approval queue" in content
        assert "Daily vulnerability digest" in content
        assert "New vulnerabilities" in content
        assert "Send test" in content
        assert "Sync now" not in content
        assert "Frameworks on your Trust Center" not in content
        assert "xoxb-live" not in content

    def test_choosing_a_channel_saves_it(self, admin_client_for_team, connected_slack, fake_slack) -> None:
        response = admin_client_for_team.post(
            reverse("integrations:panel", kwargs={"workspace_key": connected_slack.team.key}),
            {"action": "route", "provider": "slack", "event": EVENT, "channel_id": "C001"},
        )

        assert response.status_code == 200
        assert NotificationRoute.objects.get().channel_name == "security"

    def test_sending_a_test_posts(self, admin_client_for_team, connected_slack, fake_slack) -> None:
        _route(connected_slack)

        admin_client_for_team.post(
            reverse("integrations:panel", kwargs={"workspace_key": connected_slack.team.key}),
            {"action": "test", "provider": "slack", "event": EVENT},
        )

        assert len(fake_slack.posts) == 1

    def test_slack_cannot_be_synced(self, admin_client_for_team, connected_slack, monkeypatch) -> None:
        from sbomify.apps.integrations import views

        monkeypatch.setattr(views.sync_integration, "send", lambda *_: pytest.fail("queued a sync"))

        response = admin_client_for_team.post(
            reverse("integrations:panel", kwargs={"workspace_key": connected_slack.team.key}),
            {"action": "sync", "provider": "slack"},
        )

        assert response.status_code == 200
        assert response.headers.get("HX-Reswap") == "none"

    def test_a_member_may_not_choose_a_channel(self, connected_slack, fake_slack, guest_user) -> None:
        Member.objects.create(user=guest_user, team=connected_slack.team, role="member")
        client = Client()
        setup_authenticated_client_session(client, connected_slack.team, guest_user)

        client.post(
            reverse("integrations:panel", kwargs={"workspace_key": connected_slack.team.key}),
            {"action": "route", "provider": "slack", "event": EVENT, "channel_id": "C001"},
        )

        assert not NotificationRoute.objects.exists()

    def test_disconnecting_drops_every_route(self, admin_client_for_team, connected_slack) -> None:
        _route(connected_slack)

        admin_client_for_team.post(
            reverse("integrations:panel", kwargs={"workspace_key": connected_slack.team.key}),
            {"action": "disconnect", "provider": "slack"},
        )

        assert not Integration.objects.filter(provider="slack").exists()
        assert not NotificationRoute.objects.exists()


@pytest.mark.usefixtures("slack_credentials")
class TestCallback:
    def test_connecting_slack_stores_the_account_and_queues_no_sync(
        self, admin_client_for_team, sample_team_with_owner_member, monkeypatch
    ) -> None:
        from sbomify.apps.integrations import oauth, views

        team = sample_team_with_owner_member.team
        admin_client_for_team.post(
            reverse("integrations:connect", kwargs={"workspace_key": team.key, "provider": "slack"})
        )
        nonce = admin_client_for_team.session[oauth.SESSION_KEY]["nonce"]
        monkeypatch.setattr(
            oauth,
            "exchange_code",
            lambda request, provider, code: oauth.TokenSet(
                access_token="xoxb-new",
                refresh_token="",
                expires_at=None,
                scopes=SLACK.scopes,
                account={"id": "T0001", "name": "Example Slack"},
            ),
        )
        monkeypatch.setattr(views.sync_integration, "send", lambda *_: pytest.fail("queued a sync"))

        response = admin_client_for_team.get(
            reverse("integrations:callback", kwargs={"provider": "slack"}), {"code": "c", "state": nonce}
        )

        assert response.status_code == 302
        integration = Integration.objects.get(team=team, provider="slack")
        assert integration.access_token == "xoxb-new"
        assert integration.account == {"id": "T0001", "name": "Example Slack"}


class TestTheScheduler:
    def test_never_queues_a_sync_for_slack(self, connected_slack, connected_vanta, monkeypatch) -> None:
        from sbomify.apps.integrations import tasks

        queued: list[str] = []
        monkeypatch.setattr(tasks.sync_integration, "send", lambda integration_id: queued.append(integration_id))

        tasks.sync_due_integrations()

        assert queued == [connected_vanta.id]

    def test_running_a_sync_on_slack_is_refused(self, connected_slack) -> None:
        from sbomify.apps.integrations.services.sync import run_sync

        assert not run_sync(connected_slack).ok
