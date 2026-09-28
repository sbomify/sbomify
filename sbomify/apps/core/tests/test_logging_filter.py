"""Tests for the log filters wired onto the console handlers."""

import logging

import pytest

from sbomify.logging_filters import is_benign_shielded_future_error, is_on_demand_tls_ask_denial


def _make_record(message: str, *, name: str = "asyncio", level: int = logging.ERROR) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=0,
        msg=message,
        args=None,
        exc_info=None,
    )


class _Request:
    """Enough of an HttpRequest for the filter.

    ``resolver_match`` is the whole point: ``_get_response`` assigns it once a
    route matches and before the view runs, so a 404 a view returned carries one
    and a 404 from resolution failing does not.
    """

    def __init__(self, *, resolved: bool = True) -> None:
        self.resolver_match = object() if resolved else None


# What Django writes for a 404: ``log_response("%s: %s", reason_phrase, path)``
# on the ``django.request`` logger, at WARNING for any status below 500. The
# request rides along in ``extra``, which is where the filter reads it from.
def _django_request_record(message: str, *, level: int = logging.WARNING, resolved: bool = True) -> logging.LogRecord:
    record = _make_record(message, name="django.request", level=level)
    record.request = _Request(resolved=resolved)  # type: ignore[attr-defined]
    return record


ASK_PATH = "/api/v1/internal/domains"


@pytest.mark.parametrize(
    "message,expected_benign",
    [
        ("CancelledError exception in shielded future", True),
        ("ConnectionClosedError: sent 1011 (internal error) exception in shielded future", True),
        ("ConnectionClosedOK exception in shielded future", True),
        ("ValueError exception in shielded future", False),
        ("CancelledError raised in handler", False),
        ("ConnectionClosedError while reading", False),
        ("unrelated log line", False),
    ],
)
def test_is_benign_shielded_future_error(message: str, expected_benign: bool) -> None:
    record = _make_record(message)
    assert is_benign_shielded_future_error(record) is expected_benign


def test_the_on_demand_tls_ask_denial_is_dropped() -> None:
    """The single loudest line in production, and it carries no information.

    Caddy asks this endpoint before issuing a certificate for an unrecognised
    SNI, and 404 is the documented way to say "do not issue one". So every
    scanner that opens a TLS connection to our IP produces one: 49,835 of
    152,128 messages in a week of production, a third of the whole stream.

    Dropping it loses nothing. ``check_domain_allowed`` already logs each denial
    with the domain that was refused, deduplicated by the resolve cache, and
    that line is kept.
    """
    assert is_on_demand_tls_ask_denial(_django_request_record(f"Not Found: {ASK_PATH}")) is True


def test_a_server_error_on_the_ask_endpoint_still_surfaces() -> None:
    """The filter must not turn the endpoint into a blind spot.

    A 404 here is the endpoint working. A 500 here means Caddy cannot get an
    answer and will stop issuing certificates for every custom domain, which is
    a genuine outage. Django logs 5xx at ERROR, so the level check is what keeps
    the two apart.
    """
    broken = _django_request_record(f"Internal Server Error: {ASK_PATH}", level=logging.ERROR)
    assert is_on_demand_tls_ask_denial(broken) is False


def test_the_route_going_missing_is_not_a_denial() -> None:
    """The failure this filter could hide, and the reason it reads the request.

    A URL-resolver 404 writes the identical line: same logger, same path, same
    level. It means the ask endpoint is not registered, so Caddy gets no answer
    and stops issuing certificates for every custom domain. Matching on the
    message alone would swallow exactly that.
    """
    unrouted = _django_request_record(f"Not Found: {ASK_PATH}", resolved=False)
    assert is_on_demand_tls_ask_denial(unrouted) is False


def test_a_record_with_no_request_is_not_a_denial() -> None:
    """Nothing to check it against, so it stays visible."""
    bare = _make_record(f"Not Found: {ASK_PATH}", name="django.request", level=logging.WARNING)
    assert is_on_demand_tls_ask_denial(bare) is False


@pytest.mark.parametrize(
    "record",
    [
        _django_request_record("Not Found: /api/v1/sboms"),
        _django_request_record(f"Not Found: {ASK_PATH}/extra"),
        _make_record(f"On-demand TLS denied: {ASK_PATH}", name="sbomify.apps.teams.apis"),
        _django_request_record(f"Unprocessable Entity: {ASK_PATH}"),
        _django_request_record(f"Bad Request: {ASK_PATH}"),
        _django_request_record(f"Forbidden: {ASK_PATH}"),
    ],
    ids=["another 404", "a longer path", "another logger", "a 422", "a 400", "a 403"],
)
def test_nothing_else_is_dropped(record: logging.LogRecord) -> None:
    """Matching is anchored on the full path and pinned to ``django.request``.

    The "longer path" case is why the match is anchored rather than a substring
    test: ``/api/v1/internal/domains-something`` would be a different endpoint.

    The 422 is the one that matters most, and it is why the reason phrase is
    matched instead of the level. Django writes every 4xx at WARNING, and this
    endpoint answers 422 when Caddy calls it with no ``domain`` at all, which
    means the proxy is misconfigured and no custom domain will ever get a
    certificate. Keying on WARNING would have discarded it as though it were
    the routine denial.
    """
    assert is_on_demand_tls_ask_denial(record) is False
