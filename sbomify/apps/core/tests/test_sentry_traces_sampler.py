"""Sampling policy for Sentry transactions.

The WebSocket case is the one with teeth: a socket lives as long as the tab
stays open, so sampling it as a transaction records the connection lifetime as
a duration. One tab left open overnight reports as a 12-hour request and drags
every latency percentile with it.
"""

from __future__ import annotations

import pytest

from sbomify.settings import _sentry_traces_sampler as sample


class TestWebSockets:
    def test_a_websocket_is_never_sampled(self):
        """Dropped rather than rate-limited: a long-lived socket is the healthy
        case, and there is no duration here worth measuring."""
        assert sample({"asgi_scope": {"type": "websocket", "path": "/ws/workspace/abc/"}}) == 0.0

    def test_an_asgi_http_request_is_still_sampled(self):
        """The guard keys on the scope type, so it must not swallow ordinary
        ASGI traffic on the same server."""
        assert sample({"asgi_scope": {"type": "http", "path": "/dashboard"}}) > 0

    def test_a_lifespan_scope_is_still_sampled(self):
        """Only websocket is special-cased; anything else falls through."""
        assert sample({"asgi_scope": {"type": "lifespan"}}) > 0


class TestTheExistingRoutesAreUndisturbed:
    @pytest.mark.parametrize(
        "context",
        [
            {"wsgi_environ": {"PATH_INFO": "/api/v1/releases"}},
            {"wsgi_environ": {"PATH_INFO": "/x", "HTTP_HX_REQUEST": "true"}},
            {"wsgi_environ": {"PATH_INFO": "/dashboard"}},
            {"transaction_context": {"op": "dramatiq"}},
            {},
        ],
    )
    def test_everything_else_keeps_a_non_zero_rate(self, context):
        assert sample(context) > 0


def test_a_zero_base_rate_still_wins(monkeypatch):
    """Turning sampling off globally must not be re-enabled by any branch."""
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0")

    assert sample({"asgi_scope": {"type": "http"}}) == 0.0
    assert sample({"asgi_scope": {"type": "websocket"}}) == 0.0
