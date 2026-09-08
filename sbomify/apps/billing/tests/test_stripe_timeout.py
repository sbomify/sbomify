"""The bound on how long a Stripe request may take.

The library's own default is 80 seconds. Workspace settings reaches Stripe
while rendering, on every tab and twice per tab, so an unreachable Stripe held
the page past the edge's limit and the whole section answered 504 rather than
rendering from stored billing data. Syncing already fails soft, so the bound
costs nothing worse than slightly stale limits.
"""

from __future__ import annotations

import stripe
from django.conf import settings


def _library_default_timeout() -> float:
    """What one request would wait if we set nothing."""
    import inspect

    from stripe._http_client import RequestsClient

    default = inspect.signature(RequestsClient.__init__).parameters["timeout"].default
    return float(default)


def test_the_configured_timeout_is_shorter_than_the_library_default():
    """A bound no tighter than the default would not have changed anything."""
    assert settings.STRIPE_TIMEOUT_SECONDS < _library_default_timeout()


def test_two_requests_still_fit_inside_a_page_render():
    """Settings syncs twice per render, so one request may take at most half
    the budget. 30 seconds is the shortest edge timeout we sit behind."""
    assert settings.STRIPE_TIMEOUT_SECONDS * 2 < 30


def test_the_library_is_given_a_bounded_client():
    """Set on the default client rather than per call, so a request added
    later cannot reintroduce the unbounded wait by forgetting to pass it."""
    assert stripe.default_http_client is not None
    assert stripe.default_http_client._timeout == settings.STRIPE_TIMEOUT_SECONDS


def test_the_client_does_not_pin_one_session_across_threads():
    """A shared client is only safe while each thread gets its own session."""
    assert stripe.default_http_client._session is None
