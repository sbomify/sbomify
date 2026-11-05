"""Slack's side of the connection: the OAuth differences and the two API calls.

Slack answers almost everything with a 200 and reports failure in the body, so
most of these pin that a response is never trusted on its status alone.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import requests
from django.test import RequestFactory

from sbomify.apps.integrations import oauth
from sbomify.apps.integrations.exceptions import ProviderAuthError, ProviderUnavailable
from sbomify.apps.integrations.providers import slack
from sbomify.apps.integrations.providers.slack import SLACK, SlackChannelError, SlackClient


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture
def request_with_session(rf: RequestFactory):
    from django.contrib.sessions.middleware import SessionMiddleware

    request = rf.get("/", HTTP_HOST="testserver")
    SessionMiddleware(lambda r: None).process_request(request)
    return request


@pytest.mark.usefixtures("slack_credentials")
class TestSlackOAuth:
    def test_asks_for_the_bot_scopes_comma_separated(self, request_with_session) -> None:
        """Slack's authorize URL reads a comma-separated list, not the spec's spaces."""
        url = oauth.start_authorization(request_with_session, SLACK, "workspacekey1")

        params = parse_qs(urlparse(url).query)
        assert params["scope"] == ["chat:write,chat:write.public,channels:read,groups:read"]
        assert params["redirect_uri"] == ["http://testserver/integrations/oauth/slack/callback"]

    def test_the_exchange_is_form_encoded(self, monkeypatch) -> None:
        """Slack's token endpoint refuses a JSON body."""
        sent: dict = {}

        def fake_request(method, url, **kwargs):
            sent.update(kwargs)
            return _Response(
                200,
                {
                    "ok": True,
                    "access_token": "xoxb-new",
                    "token_type": "bot",
                    "scope": "chat:write,channels:read",
                    "team": {"id": "T0001", "name": "Example Slack"},
                },
            )

        monkeypatch.setattr(oauth, "request_with_retry", fake_request)

        token_set = oauth._token_request(SLACK, {"grant_type": "authorization_code", "code": "c"})

        assert "json" not in sent
        assert sent["data"]["client_secret"] == "slack_secret_test"
        assert token_set.access_token == "xoxb-new"
        assert token_set.expires_at is None
        assert token_set.scopes == ("chat:write", "channels:read")
        assert token_set.account == {"id": "T0001", "name": "Example Slack"}

    def test_a_refusal_in_a_200_is_still_a_refusal(self, monkeypatch) -> None:
        """Stored as given, ``{"ok": false}`` would become a credential that never works."""
        monkeypatch.setattr(
            oauth, "request_with_retry", lambda *a, **k: _Response(200, {"ok": False, "error": "invalid_code"})
        )

        with pytest.raises(ProviderAuthError):
            oauth._token_request(SLACK, {"code": "c"})

    def test_a_rate_limit_in_a_200_is_transient(self, monkeypatch) -> None:
        monkeypatch.setattr(
            oauth, "request_with_retry", lambda *a, **k: _Response(200, {"ok": False, "error": "ratelimited"})
        )

        with pytest.raises(ProviderUnavailable):
            oauth._token_request(SLACK, {"code": "c"})


class TestAccount:
    def test_reads_the_slack_workspace(self) -> None:
        assert slack.account({"team": {"id": "T1", "name": "Acme"}}) == {"id": "T1", "name": "Acme"}

    def test_tolerates_a_response_without_one(self) -> None:
        assert slack.account({}) == {}
        assert slack.account({"team": "T1"}) == {}


@pytest.fixture
def api(monkeypatch, settings):
    """Answers Slack Web API calls from a queue of responses, recording each call."""
    settings.SLACK_API_BASE_URL = "https://slack.example/api"
    calls: list[dict] = []
    responses: list[_Response] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return responses.pop(0)

    monkeypatch.setattr(slack, "request_with_retry", fake_request)
    return calls, responses


class TestListChannels:
    def test_follows_the_cursor_and_sorts_by_name(self, api) -> None:
        calls, responses = api
        responses += [
            _Response(
                200,
                {
                    "ok": True,
                    "channels": [{"id": "C2", "name": "security", "is_private": False}],
                    "response_metadata": {"next_cursor": "page2"},
                },
            ),
            _Response(
                200,
                {
                    "ok": True,
                    "channels": [{"id": "C1", "name": "Alerts", "is_private": True}, "junk"],
                    "response_metadata": {"next_cursor": ""},
                },
            ),
        ]

        channels = SlackClient("xoxb").list_channels()

        assert [(channel.id, channel.name, channel.is_private) for channel in channels] == [
            ("C1", "Alerts", True),
            ("C2", "security", False),
        ]
        assert calls[0]["url"] == "https://slack.example/api/conversations.list"
        assert calls[0]["headers"]["Authorization"] == "Bearer xoxb"
        assert calls[0]["params"]["exclude_archived"] == "true"
        assert calls[1]["params"]["cursor"] == "page2"

    def test_stops_at_the_page_ceiling(self, api, monkeypatch) -> None:
        """A cursor that never ends must not turn one panel load into a crawl."""
        calls, responses = api
        monkeypatch.setattr(slack, "MAX_PAGES", 2)
        page = {"ok": True, "channels": [], "response_metadata": {"next_cursor": "again"}}
        responses += [_Response(200, page), _Response(200, page)]

        SlackClient("xoxb").list_channels()

        assert len(calls) == 2


class TestErrors:
    @pytest.mark.parametrize("error", ["invalid_auth", "token_revoked", "account_inactive", "missing_scope"])
    def test_a_dead_token_is_an_auth_error(self, api, error) -> None:
        _calls, responses = api
        responses.append(_Response(200, {"ok": False, "error": error}))

        with pytest.raises(ProviderAuthError):
            SlackClient("xoxb").post_message("C1", "hi", [])

    @pytest.mark.parametrize("error", ["channel_not_found", "not_in_channel", "is_archived"])
    def test_a_refused_channel_is_about_the_channel(self, api, error) -> None:
        """One bad channel must not cost the workspace its connection."""
        _calls, responses = api
        responses.append(_Response(200, {"ok": False, "error": error}))

        with pytest.raises(SlackChannelError):
            SlackClient("xoxb").post_message("C1", "hi", [])

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_a_busy_slack_is_transient(self, api, status) -> None:
        _calls, responses = api
        responses.append(_Response(status, {}))

        with pytest.raises(ProviderUnavailable):
            SlackClient("xoxb").post_message("C1", "hi", [])

    def test_an_unknown_error_is_transient(self, api) -> None:
        _calls, responses = api
        responses.append(_Response(200, {"ok": False, "error": "fatal_error"}))

        with pytest.raises(ProviderUnavailable):
            SlackClient("xoxb").post_message("C1", "hi", [])

    def test_an_unreachable_slack_is_transient(self, monkeypatch) -> None:
        def boom(*args, **kwargs):
            raise requests.ConnectionError("dns")

        monkeypatch.setattr(slack, "request_with_retry", boom)

        with pytest.raises(ProviderUnavailable):
            SlackClient("xoxb").list_channels()

    def test_an_unreadable_body_is_transient(self, api) -> None:
        _calls, responses = api
        responses.append(_Response(200, ValueError("not json")))

        with pytest.raises(ProviderUnavailable):
            SlackClient("xoxb").list_channels()


class TestPostMessage:
    def test_posts_json_with_text_and_blocks(self, api) -> None:
        calls, responses = api
        responses.append(_Response(200, {"ok": True}))

        SlackClient("xoxb").post_message("C1", "fallback", [{"type": "divider"}])

        assert calls[0]["url"] == "https://slack.example/api/chat.postMessage"
        assert calls[0]["json"] == {
            "channel": "C1",
            "text": "fallback",
            "blocks": [{"type": "divider"}],
            "unfurl_links": False,
        }
