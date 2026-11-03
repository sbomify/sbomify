"""Tests for joining server-side PostHog events to the visitor who triggered them.

Covers the consent cookie the server reads, the browser identity it borrows
from the posthog-js cookie, and the session queue that hands person-scoped
events such as ``user:signed_up`` to the browser.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest
from allauth.account.signals import user_signed_up
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core import posthog_service
from sbomify.apps.core.analytics import events

KEY = "phc_test_key"
CONSENT = f"__ph_opt_in_out_{KEY}"
PERSISTED = f"ph_{KEY}_posthog"


def _request(cookies: dict[str, str] | None = None, authenticated: bool = False) -> Any:
    request = RequestFactory().get("/")
    request.COOKIES = cookies or {}
    request.user = MagicMock(is_authenticated=authenticated, pk=7)
    request.session = SessionStore()
    return request


def _persisted(**state: Any) -> str:
    return quote(json.dumps(state))


@pytest.fixture(autouse=True)
def _posthog_enabled() -> Iterator[None]:
    with override_settings(POSTHOG_API_KEY=KEY, POSTHOG_HOST="https://us.i.posthog.com"):
        yield


class TestConsentStatus:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1", True), ("true", True), ("0", False), ("false", False), ("maybe", None)],
    )
    def test_reads_the_posthog_js_consent_cookie(self, value: str, expected: bool | None) -> None:
        assert posthog_service.consent_status(_request({CONSENT: value})) is expected

    def test_no_cookie_means_no_choice_yet(self) -> None:
        assert posthog_service.consent_status(_request()) is None
        assert posthog_service.has_opted_out(_request()) is True

    def test_another_projects_cookie_is_ignored(self) -> None:
        assert posthog_service.consent_status(_request({"__ph_opt_in_out_phc_other": "1"})) is None


class TestBrowserIdentity:
    def test_anonymous_visitor_gets_their_browser_distinct_id(self) -> None:
        request = _request({PERSISTED: _persisted(distinct_id="anon-123"), "ph_session_id": "sess"})
        assert posthog_service.get_distinct_id(request) == "anon-123"

    def test_signed_in_user_keeps_their_pk(self) -> None:
        request = _request({PERSISTED: _persisted(distinct_id="anon-123")}, authenticated=True)
        assert posthog_service.get_distinct_id(request) == "7"

    @pytest.mark.parametrize("raw", ["not-json", quote("[1, 2]"), _persisted(distinct_id=""), "x" * 5000])
    def test_unusable_cookie_falls_back_to_the_session_cookie(self, raw: str) -> None:
        request = _request({PERSISTED: raw, "ph_session_id": "sess"})
        assert posthog_service.get_distinct_id(request) == "sess"

    def test_session_id_comes_from_the_persisted_cookie_when_the_app_has_not_set_one(self) -> None:
        request = _request({PERSISTED: _persisted(distinct_id="anon-123", **{"$sesid": [1, "sess-abc", 0]})})
        assert posthog_service.get_session_id(request) == "sess-abc"

    def test_app_session_cookie_wins_over_the_persisted_one(self) -> None:
        request = _request({PERSISTED: _persisted(**{"$sesid": [1, "sess-abc", 0]}), "ph_session_id": "sess-app"})
        assert posthog_service.get_session_id(request) == "sess-app"

    def test_server_side_capture_lands_on_the_browser_person(self) -> None:
        client = MagicMock()
        posthog_service._client, posthog_service._initialized = client, True
        try:
            request = _request({CONSENT: "1", PERSISTED: _persisted(distinct_id="anon-123", **{"$sesid": [1, "s", 0]})})
            posthog_service.capture(posthog_service.get_distinct_id(request), "test:event", request=request)
        finally:
            posthog_service._client, posthog_service._initialized = None, False
        client.capture.assert_called_once_with("anon-123", "test:event", properties={"$session_id": "s"})


class TestClientEventQueue:
    def test_events_wait_until_the_visitor_chooses(self) -> None:
        request = _request()
        posthog_service.queue_client_event(request, "user:signed_up", {"signup_method": "email"})
        assert posthog_service.take_client_events(request) == []
        request.COOKIES[CONSENT] = "1"
        assert posthog_service.take_client_events(request) == [
            {"event": "user:signed_up", "properties": {"signup_method": "email"}}
        ]
        assert posthog_service.take_client_events(request) == []

    def test_declining_drops_queued_events(self) -> None:
        request = _request()
        posthog_service.queue_client_event(request, "user:signed_up")
        request.COOKIES[CONSENT] = "0"
        assert posthog_service.take_client_events(request) == []
        request.COOKIES[CONSENT] = "1"
        assert posthog_service.take_client_events(request) == []

    def test_nothing_is_queued_for_a_visitor_who_declined(self) -> None:
        request = _request({CONSENT: "0"})
        posthog_service.queue_client_event(request, "user:signed_up")
        assert posthog_service._CLIENT_EVENTS_SESSION_KEY not in request.session

    def test_queue_keeps_only_the_latest_events(self) -> None:
        request = _request()
        for n in range(15):
            posthog_service.queue_client_event(request, f"test:{n}")
        queued = request.session[posthog_service._CLIENT_EVENTS_SESSION_KEY]
        assert [e["event"] for e in queued] == [f"test:{n}" for n in range(5, 15)]

    @override_settings(POSTHOG_API_KEY="")
    def test_disabled_deployments_queue_nothing(self) -> None:
        request = _request()
        posthog_service.queue_client_event(request, "user:signed_up")
        assert posthog_service._CLIENT_EVENTS_SESSION_KEY not in request.session


class TestSignedUpEvent:
    def _queued(self, request: Any) -> list[dict[str, Any]]:
        return list(request.session.get(posthog_service._CLIENT_EVENTS_SESSION_KEY, []))

    def test_social_signup_is_queued_with_its_provider(self) -> None:
        request = _request()
        sociallogin = MagicMock()
        sociallogin.account.provider = "keycloak"
        user_signed_up.send(sender=MagicMock, request=request, user=MagicMock(), sociallogin=sociallogin)
        assert self._queued(request) == [{"event": events.USER_SIGNED_UP, "properties": {"signup_method": "keycloak"}}]

    def test_password_signup_is_queued_as_email(self) -> None:
        request = _request()
        user_signed_up.send(sender=MagicMock, request=request, user=MagicMock())
        assert self._queued(request) == [{"event": events.USER_SIGNED_UP, "properties": {"signup_method": "email"}}]

    def test_registry_scopes_signup_to_the_person(self) -> None:
        spec = events.get_spec(events.USER_SIGNED_UP)
        assert spec is not None and spec.distinct_id_kind == "user"


@pytest.mark.django_db
class TestPageSendsQueuedEvents:
    @pytest.fixture(autouse=True)
    def _no_plan_selection(self, mocker: MockerFixture) -> None:
        mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)

    def _queue(self, client: Client) -> None:
        session = client.session
        session["current_workspace"]["has_completed_wizard"] = True
        session[posthog_service._CLIENT_EVENTS_SESSION_KEY] = [
            {"event": events.USER_SIGNED_UP, "properties": {"signup_method": "keycloak"}}
        ]
        session.save()

    def test_opted_in_page_renders_the_events_once(self, authenticated_web_client: Client) -> None:
        self._queue(authenticated_web_client)
        authenticated_web_client.cookies[CONSENT] = "1"

        first = authenticated_web_client.get(reverse("core:dashboard")).content.decode()
        assert 'id="posthog-events"' in first
        assert "user:signed_up" in first
        assert "opt_out_capturing_persistence_type: 'cookie'" in first

        second = authenticated_web_client.get(reverse("core:dashboard")).content.decode()
        assert 'id="posthog-events"' not in second

    def test_page_holds_the_events_until_the_visitor_chooses(self, authenticated_web_client: Client) -> None:
        self._queue(authenticated_web_client)

        page = authenticated_web_client.get(reverse("core:dashboard")).content.decode()
        assert 'id="posthog-events"' not in page
        assert authenticated_web_client.session[posthog_service._CLIENT_EVENTS_SESSION_KEY]
