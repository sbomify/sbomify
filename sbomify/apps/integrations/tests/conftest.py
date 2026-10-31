from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.integrations.models import Integration


@pytest.fixture
def vanta_credentials(settings):
    """A deployment that holds Vanta OAuth credentials.

    Without these the provider is "not available here" and every connect path
    short-circuits, so almost every test in this app needs them.
    """
    settings.VANTA_CLIENT_ID = "vci_test"
    settings.VANTA_CLIENT_SECRET = "vcs_test"
    settings.VANTA_OAUTH_AUTHORIZE_URL = "https://app.vanta.example/oauth/authorize"
    settings.VANTA_OAUTH_TOKEN_URL = "https://api.vanta.example/oauth/token"
    settings.VANTA_API_BASE_URL = "https://api.vanta.example"
    return settings


@pytest.fixture
def connected_vanta(sample_team_with_owner_member) -> Integration:
    return Integration.objects.create(
        team=sample_team_with_owner_member.team,
        provider=Integration.Provider.VANTA,
        access_token="vat_live",
        refresh_token="vrt_live",
        token_expires_at=timezone.now() + timedelta(hours=1),
        connected_by=sample_team_with_owner_member.user,
    )


@pytest.fixture
def admin_client_for_team(sample_team_with_owner_member) -> Client:
    client = Client()
    setup_authenticated_client_session(
        client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
    )
    return client


@pytest.fixture
def slack_credentials(settings):
    """A deployment that holds a Slack app's OAuth credentials."""
    settings.SLACK_CLIENT_ID = "1234.5678"
    settings.SLACK_CLIENT_SECRET = "slack_secret_test"
    settings.SLACK_OAUTH_AUTHORIZE_URL = "https://slack.example/oauth/v2/authorize"
    settings.SLACK_OAUTH_TOKEN_URL = "https://slack.example/api/oauth.v2.access"
    settings.SLACK_API_BASE_URL = "https://slack.example/api"
    return settings


@pytest.fixture
def connected_slack(sample_team_with_owner_member) -> Integration:
    """A Slack connection as the callback stores it: a bot token, no expiry, no refresh."""
    return Integration.objects.create(
        team=sample_team_with_owner_member.team,
        provider=Integration.Provider.SLACK,
        access_token="xoxb-live",
        account={"id": "T0001", "name": "Example Slack"},
        connected_by=sample_team_with_owner_member.user,
    )


class FakeSlack:
    """Stands in for ``SlackClient``: lists ``channels`` and records every post.

    ``fail_with`` makes every call raise it, which is how a test plays Slack
    refusing or not answering.
    """

    def __init__(self) -> None:
        from sbomify.apps.integrations.providers.slack import Channel

        self.channels = [
            Channel(id="C001", name="security", is_private=False),
            Channel(id="C002", name="vex-review", is_private=True),
        ]
        self.posts: list[dict] = []
        self.fail_with: Exception | None = None
        self.list_calls = 0

    def __call__(self, token: str) -> "FakeSlack":
        self.token = token
        return self

    def list_channels(self):
        self.list_calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return list(self.channels)

    def post_message(self, channel_id: str, text: str, blocks: list) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.posts.append({"channel": channel_id, "text": text, "blocks": blocks})


@pytest.fixture
def fake_slack(monkeypatch) -> FakeSlack:
    from django.core.cache import cache

    from sbomify.apps.integrations.services import notifications

    cache.clear()
    fake = FakeSlack()
    monkeypatch.setattr(notifications, "SlackClient", fake)
    return fake
