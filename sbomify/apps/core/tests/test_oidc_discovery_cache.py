"""A blip at Keycloak must not stop people logging in.

allauth memoises the OpenID Connect discovery document on the adapter and
builds a new adapter per request, so every sign-in waited on a live read of
``.well-known/openid-configuration``. When that read failed -- a 521 from the
CDN in front of Keycloak, or a read timeout -- the exception came straight
back as a 500 on ``/accounts/oidc/keycloak/login/``.

The document is deployment configuration, so these pin the two properties
that remove the dependency: logins stop re-reading it, and a login still
works while the provider is unreachable.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests
from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter
from django.core.cache import cache

from sbomify.apps.core.adapters import (
    OIDC_CONFIG_REFRESH_AFTER,
    OIDC_CONFIG_RETRY_AFTER_FAILURE,
    cached_openid_config,
)

SERVER_URL = "https://kc.example.test/realms/sbomify/.well-known/openid-configuration"
DOCUMENT = {
    "issuer": "https://kc.example.test/realms/sbomify",
    "authorization_endpoint": "https://kc.example.test/realms/sbomify/protocol/openid-connect/auth",
    "token_endpoint": "https://kc.example.test/realms/sbomify/protocol/openid-connect/token",
    "userinfo_endpoint": "https://kc.example.test/realms/sbomify/protocol/openid-connect/userinfo",
    "jwks_uri": "https://kc.example.test/realms/sbomify/protocol/openid-connect/certs",
}


class _Adapter:
    """Only the part of the allauth adapter the property actually reads."""

    def __init__(self, server_url: str = SERVER_URL) -> None:
        self._server_url = server_url

    def get_provider(self) -> Any:
        return type("Provider", (), {"server_url": self._server_url})()


@pytest.fixture(autouse=True)
def _clear_cache() -> Any:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def fetches(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every discovery read, serving the document to each."""
    calls: list[str] = []

    def _fetch(server_url: str) -> dict[str, Any]:
        calls.append(server_url)
        return dict(DOCUMENT)

    monkeypatch.setattr("sbomify.apps.core.adapters._fetch_openid_config", _fetch)
    return calls


class TestTheDocumentIsReadOnceNotPerLogin:
    def test_a_second_adapter_reuses_the_cached_document(self, fetches: list[str]) -> None:
        assert cached_openid_config(_Adapter()) == DOCUMENT
        assert cached_openid_config(_Adapter()) == DOCUMENT

        assert fetches == [SERVER_URL]

    def test_one_adapter_reads_it_once_across_its_properties(self, fetches: list[str]) -> None:
        adapter = _Adapter()

        cached_openid_config(adapter)
        cached_openid_config(adapter)

        assert fetches == [SERVER_URL]

    def test_a_different_provider_is_cached_separately(self, fetches: list[str]) -> None:
        other = "https://kc.example.test/realms/other/.well-known/openid-configuration"

        cached_openid_config(_Adapter())
        cached_openid_config(_Adapter(other))

        assert fetches == [SERVER_URL, other]

    def test_the_document_is_re_read_once_it_goes_stale(
        self, fetches: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cached_openid_config(_Adapter())

        now = __import__("time").time() + OIDC_CONFIG_REFRESH_AFTER + 1
        monkeypatch.setattr("sbomify.apps.core.adapters.time.time", lambda: now)
        cached_openid_config(_Adapter())

        assert fetches == [SERVER_URL, SERVER_URL]


class TestALoginSurvivesAnUnreachableProvider:
    @pytest.mark.parametrize(
        "failure",
        [
            requests.HTTPError("521 Server Error: <none>"),
            requests.ReadTimeout("Read timed out. (read timeout=5)"),
        ],
    )
    def test_the_cached_copy_is_served_when_the_refresh_fails(
        self, fetches: list[str], monkeypatch: pytest.MonkeyPatch, failure: Exception
    ) -> None:
        cached_openid_config(_Adapter())

        def _fail(server_url: str) -> dict[str, Any]:
            raise failure

        now = __import__("time").time() + OIDC_CONFIG_REFRESH_AFTER + 1
        monkeypatch.setattr("sbomify.apps.core.adapters.time.time", lambda: now)
        monkeypatch.setattr("sbomify.apps.core.adapters._fetch_openid_config", _fail)

        assert cached_openid_config(_Adapter()) == DOCUMENT

    def test_the_failure_is_not_re_attempted_on_every_login(
        self, fetches: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale entry plus a dead provider must not cost every login a timeout.

        Serving the cached copy without recording anything left ``fetched_at``
        untouched, so the entry stayed stale and the next sign-in made the same
        request and waited out the same timeout. The 500 was gone; the delay
        was not, and it was now one request per sign-in against a provider
        already in trouble.
        """
        cached_openid_config(_Adapter())
        assert fetches == [SERVER_URL]

        def _fail(server_url: str) -> dict[str, Any]:
            fetches.append(server_url)
            raise requests.ReadTimeout("Read timed out. (read timeout=5)")

        stale = __import__("time").time() + OIDC_CONFIG_REFRESH_AFTER + 1
        monkeypatch.setattr("sbomify.apps.core.adapters.time.time", lambda: stale)
        monkeypatch.setattr("sbomify.apps.core.adapters._fetch_openid_config", _fail)

        # The login that discovers the outage pays for one attempt.
        assert cached_openid_config(_Adapter()) == DOCUMENT
        assert len(fetches) == 2

        # Every login during the backoff is served from the cache, untouched.
        for _ in range(5):
            assert cached_openid_config(_Adapter()) == DOCUMENT
        assert len(fetches) == 2, "a login inside the backoff window re-attempted the fetch"

    def test_the_refresh_resumes_once_the_backoff_lapses(
        self, fetches: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The backoff rides out a blip; it must not stop noticing a recovery."""
        cached_openid_config(_Adapter())

        def _fail(server_url: str) -> dict[str, Any]:
            fetches.append(server_url)
            raise requests.ReadTimeout("Read timed out. (read timeout=5)")

        stale = __import__("time").time() + OIDC_CONFIG_REFRESH_AFTER + 1
        monkeypatch.setattr("sbomify.apps.core.adapters.time.time", lambda: stale)
        monkeypatch.setattr("sbomify.apps.core.adapters._fetch_openid_config", _fail)
        cached_openid_config(_Adapter())
        assert len(fetches) == 2

        # Past the retry deadline, and the provider is back.
        recovered = dict(DOCUMENT, token_endpoint="https://kc.example.test/new/token")

        def _succeed(server_url: str) -> dict[str, Any]:
            fetches.append(server_url)
            return recovered

        monkeypatch.setattr(
            "sbomify.apps.core.adapters.time.time",
            lambda: stale + OIDC_CONFIG_RETRY_AFTER_FAILURE + 1,
        )
        monkeypatch.setattr("sbomify.apps.core.adapters._fetch_openid_config", _succeed)

        assert cached_openid_config(_Adapter()) == recovered
        assert len(fetches) == 3

    def test_a_cold_cache_still_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With nothing cached there is no endpoint to send anyone to."""

        def _fail(server_url: str) -> dict[str, Any]:
            raise requests.ReadTimeout("Read timed out. (read timeout=5)")

        monkeypatch.setattr("sbomify.apps.core.adapters._fetch_openid_config", _fail)

        with pytest.raises(requests.ReadTimeout):
            cached_openid_config(_Adapter())


class TestAMalformedDocumentIsNotRemembered:
    def test_a_200_without_endpoints_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keycloak serves an error body with a 200 while a realm is starting."""

        class _Response:
            @staticmethod
            def raise_for_status() -> None:
                return None

            @staticmethod
            def json() -> dict[str, Any]:
                return {"error": "realm not ready"}

        class _Session:
            def __enter__(self) -> _Session:
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

            def get(self, url: str) -> _Response:
                return _Response()

        monkeypatch.setattr(
            "sbomify.apps.core.adapters.get_adapter",
            lambda: type("A", (), {"get_requests_session": staticmethod(_Session)})(),
        )

        with pytest.raises(ValueError, match="usable OpenID Connect discovery document"):
            cached_openid_config(_Adapter())


def test_the_provider_uses_the_cached_property() -> None:
    assert OpenIDConnectOAuth2Adapter.openid_config.fget is cached_openid_config
