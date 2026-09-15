"""The authorization-code flow: state handling and token parsing."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from django.test import RequestFactory
from django.utils import timezone

from sbomify.apps.integrations import oauth
from sbomify.apps.integrations.exceptions import ProviderAuthError, ProviderUnavailable
from sbomify.apps.integrations.providers.vanta import VANTA


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
    # Deliberately not saved: an unsaved SessionStore is an in-memory dict, so
    # the flow can be exercised without a database.
    return request


@pytest.mark.usefixtures("vanta_credentials")
class TestAuthorizationUrl:
    def test_carries_every_parameter_the_provider_needs(self, request_with_session) -> None:
        url = oauth.start_authorization(request_with_session, VANTA, "workspacekey1")

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == VANTA.authorize_url
        assert params["client_id"] == ["vci_test"]
        assert params["response_type"] == ["code"]
        assert params["scope"] == ["vanta-api.all:read"]
        assert params["redirect_uri"] == ["http://testserver/integrations/oauth/vanta/callback"]
        assert params["state"] == [request_with_session.session[oauth.SESSION_KEY]["nonce"]]

    def test_redirect_uri_has_no_workspace_in_it(self, request_with_session) -> None:
        """Providers register one exact callback, so the workspace cannot be in the path."""
        url = oauth.start_authorization(request_with_session, VANTA, "workspacekey1")
        redirect_uri = parse_qs(urlparse(url).query)["redirect_uri"][0]
        assert "workspacekey1" not in redirect_uri


@pytest.mark.usefixtures("vanta_credentials")
class TestConsumeState:
    def test_round_trips_the_workspace(self, request_with_session) -> None:
        oauth.start_authorization(request_with_session, VANTA, "workspacekey1")
        nonce = request_with_session.session[oauth.SESSION_KEY]["nonce"]

        assert oauth.consume_state(request_with_session, VANTA, nonce) == "workspacekey1"

    def test_is_single_use(self, request_with_session) -> None:
        """A replayed callback must not connect a second time."""
        oauth.start_authorization(request_with_session, VANTA, "workspacekey1")
        nonce = request_with_session.session[oauth.SESSION_KEY]["nonce"]

        assert oauth.consume_state(request_with_session, VANTA, nonce) == "workspacekey1"
        assert oauth.consume_state(request_with_session, VANTA, nonce) is None

    def test_rejects_a_state_that_does_not_match(self, request_with_session) -> None:
        oauth.start_authorization(request_with_session, VANTA, "workspacekey1")

        assert oauth.consume_state(request_with_session, VANTA, "not-the-nonce") is None

    def test_a_rejected_state_is_also_cleared(self, request_with_session) -> None:
        """A nonce that failed one check must not be available for a second go."""
        oauth.start_authorization(request_with_session, VANTA, "workspacekey1")
        nonce = request_with_session.session[oauth.SESSION_KEY]["nonce"]

        assert oauth.consume_state(request_with_session, VANTA, "wrong") is None
        assert oauth.consume_state(request_with_session, VANTA, nonce) is None

    def test_rejects_an_empty_state(self, request_with_session) -> None:
        oauth.start_authorization(request_with_session, VANTA, "workspacekey1")

        assert oauth.consume_state(request_with_session, VANTA, "") is None

    def test_rejects_a_stale_flow(self, request_with_session) -> None:
        oauth.start_authorization(request_with_session, VANTA, "workspacekey1")
        pending = request_with_session.session[oauth.SESSION_KEY]
        pending["started_at"] = (timezone.now() - oauth.STATE_MAX_AGE - timedelta(minutes=1)).isoformat()
        request_with_session.session[oauth.SESSION_KEY] = pending

        assert oauth.consume_state(request_with_session, VANTA, pending["nonce"]) is None

    def test_rejects_a_flow_started_for_another_provider(self, request_with_session) -> None:
        from dataclasses import replace

        other = replace(VANTA, key="other")
        oauth.start_authorization(request_with_session, other, "workspacekey1")
        nonce = request_with_session.session[oauth.SESSION_KEY]["nonce"]

        assert oauth.consume_state(request_with_session, VANTA, nonce) is None

    def test_rejects_a_callback_with_no_flow_at_all(self, request_with_session) -> None:
        assert oauth.consume_state(request_with_session, VANTA, "anything") is None


@pytest.mark.usefixtures("vanta_credentials")
class TestTokenRequests:
    def test_exchange_sends_the_grant_and_parses_the_token(self, request_with_session, monkeypatch) -> None:
        captured: dict[str, object] = {}

        def fake_request(method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            captured["headers"] = kwargs.get("headers")
            return _Response(
                200,
                {
                    "access_token": "vat_new",
                    "refresh_token": "vrt_new",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "vanta-api.all:read",
                },
            )

        monkeypatch.setattr(oauth, "request_with_retry", fake_request)

        token_set = oauth.exchange_code(request_with_session, VANTA, "vac_code")

        assert captured["method"] == "POST"
        assert captured["url"] == VANTA.token_url
        assert captured["json"]["grant_type"] == "authorization_code"
        assert captured["json"]["code"] == "vac_code"
        assert captured["json"]["client_secret"] == "vcs_test"
        # Vanta rejects form encoding outright.
        assert captured["headers"]["Content-Type"] == "application/json"

        assert token_set.access_token == "vat_new"
        assert token_set.refresh_token == "vrt_new"
        assert token_set.scopes == ("vanta-api.all:read",)
        assert token_set.expires_at is not None
        assert token_set.expires_at > timezone.now()

    def test_refresh_sends_the_refresh_grant(self, monkeypatch) -> None:
        captured: dict[str, object] = {}

        def fake_request(method, url, **kwargs):
            captured["json"] = kwargs.get("json")
            return _Response(200, {"access_token": "vat_two", "refresh_token": "vrt_two", "expires_in": 3600})

        monkeypatch.setattr(oauth, "request_with_retry", fake_request)

        token_set = oauth.refresh(VANTA, "vrt_one")

        assert captured["json"]["grant_type"] == "refresh_token"
        assert captured["json"]["refresh_token"] == "vrt_one"
        assert token_set.access_token == "vat_two"

    def test_falls_back_to_the_requested_scopes_when_none_come_back(self, monkeypatch) -> None:
        monkeypatch.setattr(
            oauth, "request_with_retry", lambda *a, **k: _Response(200, {"access_token": "vat", "expires_in": 60})
        )

        token_set = oauth.refresh(VANTA, "vrt_one")

        assert token_set.scopes == VANTA.scopes
        assert token_set.refresh_token == ""

    @pytest.mark.parametrize("status", [400, 401, 403])
    def test_a_refused_grant_is_terminal(self, monkeypatch, status) -> None:
        """A 4xx is the provider answering, and for a grant that is a refusal."""
        monkeypatch.setattr(oauth, "request_with_retry", lambda *a, **k: _Response(status, {"error": "invalid_grant"}))

        with pytest.raises(ProviderAuthError):
            oauth.refresh(VANTA, "vrt_one")

    def test_a_refusal_does_not_echo_the_error_body(self, monkeypatch) -> None:
        """The body can repeat the client secret back, so it must not surface."""
        monkeypatch.setattr(
            oauth,
            "request_with_retry",
            lambda *a, **k: _Response(400, {"error": "invalid_client", "client_secret": "vcs_test"}),
        )

        with pytest.raises(ProviderAuthError) as exc:
            oauth.refresh(VANTA, "vrt_one")

        assert "vcs_test" not in exc.value.detail

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_a_server_error_is_not_a_credential_problem(self, monkeypatch, status) -> None:
        """A bad minute at the provider must not cost the workspace its connection."""
        monkeypatch.setattr(oauth, "request_with_retry", lambda *a, **k: _Response(status, {}))

        with pytest.raises(ProviderUnavailable):
            oauth.refresh(VANTA, "vrt_one")

    def test_an_unreachable_provider_is_transient(self, monkeypatch) -> None:
        def boom(*args, **kwargs):
            raise requests.ConnectionError("no route")

        monkeypatch.setattr(oauth, "request_with_retry", boom)

        with pytest.raises(ProviderUnavailable):
            oauth.refresh(VANTA, "vrt_one")

    def test_a_response_with_no_access_token_is_transient(self, monkeypatch) -> None:
        monkeypatch.setattr(oauth, "request_with_retry", lambda *a, **k: _Response(200, {"expires_in": 60}))

        with pytest.raises(ProviderUnavailable):
            oauth.refresh(VANTA, "vrt_one")

    def test_a_non_json_response_is_transient(self, monkeypatch) -> None:
        monkeypatch.setattr(oauth, "request_with_retry", lambda *a, **k: _Response(200, ValueError("not json")))

        with pytest.raises(ProviderUnavailable):
            oauth.refresh(VANTA, "vrt_one")

    def test_the_transient_half_is_not_the_terminal_one(self) -> None:
        """The two must not be catchable as each other, or the split does nothing."""
        assert not issubclass(ProviderUnavailable, ProviderAuthError)
        assert not issubclass(ProviderAuthError, ProviderUnavailable)
