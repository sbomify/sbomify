"""The LOGGING wiring itself, not the predicates underneath it.

The filters are only worth anything if they are actually attached to the handler
production writes through. A renamed filter key or a handler that loses its
``filters`` list would leave stdout as noisy as it was while every unit test for
the predicates kept passing, and the only place that shows up is a Slack channel
nobody reads. So this drives records through a real ``dictConfig`` built from the
real ``settings.LOGGING``.
"""

from __future__ import annotations

import io
import logging
import logging.config
from collections.abc import Iterator

import pytest
from django.conf import settings

ASK_PATH = "/api/v1/internal/domains"


def _routed(*, resolved: bool = True) -> dict[str, object]:
    """The ``extra`` Django attaches to a response log line.

    ``log_response`` passes the request every time, and the filter reads
    ``resolver_match`` off it to tell the endpoint answering 404 from the route
    having gone missing. Logging without it is not a shape production produces.
    """

    class _Request:
        resolver_match = object() if resolved else None

    return {"request": _Request()}


RECONNECT = "Consumer encountered a connection error: Error 111 connecting to redis"


@pytest.fixture
def console() -> Iterator[io.StringIO]:
    """The real LOGGING config, with the console handler pointed at a buffer."""
    from sbomify.sentry_config import _last_reported

    _last_reported.clear()
    buffer = io.StringIO()
    config = {**settings.LOGGING, "handlers": dict(settings.LOGGING["handlers"])}
    config["handlers"]["console"] = {**config["handlers"]["console"], "stream": buffer}
    config["handlers"]["console_asyncio"] = {**config["handlers"]["console_asyncio"], "stream": buffer}
    logging.config.dictConfig(config)
    try:
        yield buffer
    finally:
        _last_reported.clear()
        logging.config.dictConfig(settings.LOGGING)


def _lines(buffer: io.StringIO) -> list[str]:
    return [line for line in buffer.getvalue().splitlines() if line.strip()]


def test_the_expected_tls_denial_never_reaches_stdout(console: io.StringIO) -> None:
    logging.getLogger("django.request").warning("Not Found: %s", ASK_PATH, extra=_routed())

    assert _lines(console) == []


def test_the_ask_route_going_missing_does_reach_stdout(console: io.StringIO) -> None:
    """The same line, and the one case that must never be swallowed.

    A URL-resolver 404 writes it too, and it means Caddy gets no answer and
    stops issuing certificates for every custom domain.
    """
    logging.getLogger("django.request").warning("Not Found: %s", ASK_PATH, extra=_routed(resolved=False))

    assert len(_lines(console)) == 1


@pytest.mark.parametrize(
    "level,message",
    [
        (logging.WARNING, "Not Found: /api/v1/sboms"),
        (logging.WARNING, f"Unprocessable Entity: {ASK_PATH}"),
        (logging.ERROR, f"Internal Server Error: {ASK_PATH}"),
    ],
    ids=["a real 404", "the ask endpoint called wrong", "the ask endpoint broken"],
)
def test_every_other_response_still_reaches_stdout(console: io.StringIO, level: int, message: str) -> None:
    """The two ask-path cases are the ones the filter must not swallow.

    A 422 means Caddy is calling the endpoint without a ``domain`` and a 500
    means it cannot get an answer at all. Either way no custom domain gets a
    certificate, and neither is the routine denial.
    """
    logging.getLogger("django.request").log(level, message)

    assert len(_lines(console)) == 1


def test_a_repeating_self_healing_notice_is_collapsed(console: io.StringIO) -> None:
    """Six reconnect lines from one queue, one line out.

    This is the volume fix: the reconnect loop writes one of these a second, per
    queue, for as long as the broker is unreachable.
    """
    for _ in range(6):
        logging.getLogger("dramatiq.worker.ConsumerThread(plugins)").critical(RECONNECT)

    assert len(_lines(console)) == 1


def test_a_recovered_blip_raises_no_sustained_fault(console: io.StringIO) -> None:
    """Nothing on ``sbomify.resilience``, which is what Slack alerts on.

    One blip, six processes' worth of first lines. Each is kept for the record,
    and none of them is the fault still failing.
    """
    for queue in ("plugins", "billing", "default", "vex_drift", "token_expiry", "user_purge_cron"):
        logging.getLogger(f"dramatiq.worker.ConsumerThread({queue})").critical(RECONNECT)

    assert not [line for line in _lines(console) if "sbomify.resilience" in line]


def test_a_fault_that_outlives_the_window_does_raise_one(console: io.StringIO) -> None:
    from sbomify.sentry_config import _OUTAGE_REPORT_INTERVAL_SECONDS, _last_reported

    logger = logging.getLogger("dramatiq.worker.ConsumerThread(plugins)")
    logger.critical(RECONNECT)
    for key in _last_reported:
        _last_reported[key] -= _OUTAGE_REPORT_INTERVAL_SECONDS + 1
    logger.critical(RECONNECT)

    sustained = [line for line in _lines(console) if "sbomify.resilience" in line]
    assert len(sustained) == 1
    assert "ERROR" in sustained[0]
