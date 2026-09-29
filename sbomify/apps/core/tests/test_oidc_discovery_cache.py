"""A slow or unhappy identity provider should cost latency, not the login page.

allauth memoises the OpenID Connect discovery document on the adapter instance,
and it builds one adapter per request, so every login and every callback made a
blocking HTTPS GET to Keycloak's ``.well-known`` endpoint before it could
redirect. Production saw both ends of that: read timeouts at the five-second
limit, and 521s from the provider's edge. Either one reached the user as a 500
on the one page they cannot route around.

What is pinned here is the pair. Caching the document takes the fetch out of
almost every login, and keeping the last good copy covers the fetches that still
fail. Dropping either half puts the provider's worst minute back in front of the
login page.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from django.core.cache import cache

from sbomify.apps.core import adapters
from sbomify.apps.core.adapters import cached_openid_config, load_openid_config

SERVER_URL = "https://auth.example.com/realms/prod/.well-known/openid-configuration"

DISCOVERY_DOCUMENT: dict[str, Any] = {
    "authorization_endpoint": "https://auth.example.com/realms/prod/protocol/openid-connect/auth",
    "token_endpoint": "https://auth.example.com/realms/prod/protocol/openid-connect/token",
    "userinfo_endpoint": "https://auth.example.com/realms/prod/protocol/openid-connect/userinfo",
}


class _Session:
    """The bit of ``get_requests_session()`` this code path uses."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def get(self, url: str) -> Any:
        self.calls += 1
        outcome = self._responses.pop(0) if self._responses else self._responses
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(payload: Any, error: Exception | None = None) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.side_effect = error
    return resp


@contextmanager
def _provider_answering(monkeypatch: pytest.MonkeyPatch, *responses: Any):
    """Point ``load_openid_config`` at a provider that answers as given."""
    session = _Session(list(responses))

    @contextmanager
    def _session_cm():
        yield session

    adapter = MagicMock()
    adapter.get_requests_session.side_effect = _session_cm
    monkeypatch.setattr(adapters, "get_adapter", lambda: adapter)
    yield session


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_discovery_document_is_fetched_once_and_then_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fetch that used to sit in front of every login happens once.

    This is the whole latency argument: the second login does not touch the
    provider at all, so the provider's response time stops being the login
    page's response time.
    """
    with _provider_answering(monkeypatch, _response(DISCOVERY_DOCUMENT), _response(DISCOVERY_DOCUMENT)) as session:
        assert load_openid_config(SERVER_URL) == DISCOVERY_DOCUMENT
        assert load_openid_config(SERVER_URL) == DISCOVERY_DOCUMENT

    assert session.calls == 1


def test_a_timed_out_refetch_serves_the_last_good_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production symptom, in the shape Sentry recorded it.

    A read timeout against the provider used to propagate out of the login view.
    With a document already known, the login proceeds on it instead.
    """
    with _provider_answering(monkeypatch, _response(DISCOVERY_DOCUMENT)):
        load_openid_config(SERVER_URL)

    cache.delete(adapters._oidc_discovery_cache_keys(SERVER_URL)[0])

    timeout = requests.exceptions.ReadTimeout("Read timed out. (read timeout=5)")
    with _provider_answering(monkeypatch, timeout):
        assert load_openid_config(SERVER_URL) == DISCOVERY_DOCUMENT


def test_an_http_error_on_refetch_serves_the_last_good_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the same symptom: the provider's edge returning 521."""
    with _provider_answering(monkeypatch, _response(DISCOVERY_DOCUMENT)):
        load_openid_config(SERVER_URL)

    cache.delete(adapters._oidc_discovery_cache_keys(SERVER_URL)[0])

    failing = _response(None, error=requests.exceptions.HTTPError("521 Server Error"))
    with _provider_answering(monkeypatch, failing):
        assert load_openid_config(SERVER_URL) == DISCOVERY_DOCUMENT


def test_a_failure_with_nothing_cached_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no answer to invent on a cold cache, so the error stands.

    Worth pinning: a fallback that quietly returned an empty document would turn
    a loud 500 into a login that redirects somewhere meaningless.
    """
    timeout = requests.exceptions.ReadTimeout("Read timed out. (read timeout=5)")
    with _provider_answering(monkeypatch, timeout):
        with pytest.raises(requests.exceptions.ReadTimeout):
            load_openid_config(SERVER_URL)


def test_an_unusable_document_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 carrying JSON we cannot act on must not become the cached answer.

    A proxy error page or a realm that is still starting can answer 200 with
    valid JSON. Caching that would hold the failure open for the full cache
    window, long after the provider recovered.
    """
    with _provider_answering(monkeypatch, _response({"issuer": "https://auth.example.com/realms/prod"})):
        with pytest.raises(ValueError):
            load_openid_config(SERVER_URL)

    with _provider_answering(monkeypatch, _response(DISCOVERY_DOCUMENT)) as session:
        assert load_openid_config(SERVER_URL) == DISCOVERY_DOCUMENT
    assert session.calls == 1


def test_two_providers_do_not_share_a_cached_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cache key is the discovery URL, so a changed realm is a new lookup."""
    other_url = "https://auth.example.com/realms/stage/.well-known/openid-configuration"
    other_document = {**DISCOVERY_DOCUMENT, "token_endpoint": "https://auth.example.com/realms/stage/token"}

    with _provider_answering(monkeypatch, _response(DISCOVERY_DOCUMENT)):
        load_openid_config(SERVER_URL)
    with _provider_answering(monkeypatch, _response(other_document)):
        assert load_openid_config(other_url) == other_document
    assert load_openid_config(SERVER_URL) == DISCOVERY_DOCUMENT


def test_allauth_reads_the_cached_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """The patch is installed on the class allauth actually builds per request.

    Without this the rest of the file would pass while every login still went
    straight to the provider.
    """
    from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter

    assert OpenIDConnectOAuth2Adapter.openid_config.fget is cached_openid_config

    instance = OpenIDConnectOAuth2Adapter.__new__(OpenIDConnectOAuth2Adapter)
    provider = MagicMock()
    provider.server_url = SERVER_URL
    monkeypatch.setattr(instance, "get_provider", lambda: provider, raising=False)

    with _provider_answering(monkeypatch, _response(DISCOVERY_DOCUMENT)) as session:
        assert instance.openid_config == DISCOVERY_DOCUMENT
        # Memoised on the instance, so the several properties that read it
        # within one request do not each go to the cache.
        assert instance.openid_config == DISCOVERY_DOCUMENT
    assert session.calls == 1
