"""Per-IP throttling for the surfaces the token throttle cannot reach.

``AccessTokenRateThrottle`` keys on the resolved token row, so every public
route (Trust Center, the ``auth=None`` ninja endpoints, the document
access-request POST, the OIDC exchange) had no limit of any kind.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from sbomify.apps.access_tokens.throttling import AccessTokenRateThrottle, AnonymousIPRateThrottle


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _request(remote_addr: str = "203.0.113.7", **meta):
    request = RequestFactory().get("/api/v1/anything")
    request.META["REMOTE_ADDR"] = remote_addr
    request.META.update(meta)
    return request


class TestKeying:
    def test_an_anonymous_request_gets_a_key(self):
        assert AnonymousIPRateThrottle().get_cache_key(_request()) is not None

    def test_two_ips_get_separate_budgets(self):
        throttle = AnonymousIPRateThrottle()

        assert throttle.get_cache_key(_request("203.0.113.7")) != throttle.get_cache_key(_request("203.0.113.8"))

    def test_a_token_request_is_left_to_the_token_throttle(self):
        """Otherwise one authenticated call is charged to two budgets."""
        request = _request()
        request.access_token_record = object()

        assert AnonymousIPRateThrottle().get_cache_key(request) is None

    def test_the_two_throttles_never_key_the_same_request(self):
        anon, token = AnonymousIPRateThrottle(), AccessTokenRateThrottle()
        anonymous_request = _request()

        assert anon.get_cache_key(anonymous_request) is not None
        assert token.get_cache_key(anonymous_request) is None

    def test_its_window_is_separate_from_the_token_throttle(self):
        """A shared prefix would make the two read and write one counter."""
        assert AnonymousIPRateThrottle.cache_key_prefix != AccessTokenRateThrottle.cache_key_prefix


class TestFailureModes:
    def test_an_unidentifiable_caller_is_still_throttled(self):
        """A security control that switches itself off when the environment is
        misconfigured is worse than one that occasionally over-throttles."""
        throttle = AnonymousIPRateThrottle()
        request = RequestFactory().get("/api/v1/anything")
        request.META.pop("REMOTE_ADDR", None)

        assert throttle.get_cache_key(request) is not None

    def test_unidentifiable_callers_share_one_bucket(self):
        throttle = AnonymousIPRateThrottle(rate="2/min")

        def anonymous():
            request = RequestFactory().get("/api/v1/anything")
            request.META.pop("REMOTE_ADDR", None)
            return request

        allowed = [throttle.allow_request(anonymous()) for _ in range(3)]

        assert allowed == [True, True, False]


class TestSpoofing:
    def test_x_real_ip_from_an_untrusted_peer_is_ignored(self):
        """Honouring it unconditionally would let a caller rotate the header to
        mint a fresh budget per request."""
        throttle = AnonymousIPRateThrottle()
        spoofed = throttle.get_cache_key(_request("203.0.113.7", HTTP_X_REAL_IP="198.51.100.1"))
        plain = throttle.get_cache_key(_request("203.0.113.7"))

        assert spoofed == plain

    @override_settings(TRUSTED_PROXIES=["203.0.113.7"])
    def test_a_trusted_proxy_is_honoured(self):
        """Behind Caddy the peer is the proxy for everyone, so without this the
        whole internet would share a single budget."""
        throttle = AnonymousIPRateThrottle()
        forwarded = throttle.get_cache_key(_request("203.0.113.7", HTTP_X_REAL_IP="198.51.100.1"))
        direct = throttle.get_cache_key(_request("203.0.113.7"))

        assert forwarded != direct


class TestEnforcement:
    def test_the_budget_runs_out(self):
        throttle = AnonymousIPRateThrottle(rate="3/min")
        request = _request()

        allowed = [throttle.allow_request(request) for _ in range(4)]

        assert allowed == [True, True, True, False]

    def test_one_ip_running_out_does_not_block_another(self):
        throttle = AnonymousIPRateThrottle(rate="2/min")
        for _ in range(3):
            throttle.allow_request(_request("203.0.113.7"))

        assert throttle.allow_request(_request("203.0.113.9")) is True

    def test_it_reports_a_budget_for_the_headers(self):
        """RateLimitHeadersMiddleware reads this to emit X-RateLimit-*, which
        previously only ever described token calls."""
        throttle = AnonymousIPRateThrottle(rate="5/min")
        request = _request()

        throttle.allow_request(request)

        limit, remaining, reset = request._access_token_ratelimit
        assert (limit, remaining) == (5, 4)
        assert reset > 0
