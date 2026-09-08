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


class TestTimeoutFromTheEnvironment:
    """A typo in deployment config must not crash startup or remove the bound."""

    @staticmethod
    def _parse(value):
        from sbomify.settings import _env_positive_float

        return _env_positive_float(value, 10.0)

    def test_a_normal_value_is_used(self):
        assert self._parse("2.5") == 2.5

    def test_an_unset_value_takes_the_default(self):
        assert self._parse(None) == 10.0

    def test_a_malformed_value_takes_the_default(self):
        """float("abc") would raise at import and take the process down."""
        assert self._parse("abc") == 10.0
        assert self._parse("") == 10.0

    def test_a_non_positive_value_takes_the_default(self):
        """requests raises on a negative timeout, and zero would mean no wait."""
        assert self._parse("-1") == 10.0
        assert self._parse("0") == 10.0

    def test_infinity_and_nan_take_the_default(self):
        """Infinity is the unbounded wait this setting exists to remove."""
        assert self._parse("inf") == 10.0
        assert self._parse("-inf") == 10.0
        assert self._parse("nan") == 10.0


class TestUsableTimeout:
    """What may reach the Stripe client when a settings module sets the value
    directly, rather than through the environment."""

    @staticmethod
    def _usable(value):
        from sbomify.apps.billing.apps import usable_timeout

        return usable_timeout(value)

    def test_a_number_is_returned_as_a_float(self):
        assert self._usable(10) == 10.0
        assert self._usable(2.5) == 2.5

    def test_a_bool_is_rejected(self):
        """bool subclasses int, so True would install a one second timeout."""
        assert self._usable(True) is None
        assert self._usable(False) is None

    def test_a_non_number_is_rejected(self):
        assert self._usable("10") is None
        assert self._usable(None) is None

    def test_a_non_positive_value_is_rejected(self):
        assert self._usable(0) is None
        assert self._usable(-1) is None

    def test_infinity_and_nan_are_rejected(self):
        assert self._usable(float("inf")) is None
        assert self._usable(float("-inf")) is None
        assert self._usable(float("nan")) is None
