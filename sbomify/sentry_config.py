"""Pure helpers for Sentry startup wiring.

Extracted from ``settings.py`` so regression tests can pin the actual
resolution logic instead of duplicating it locally.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any


def resolve_environment(*, debug: bool) -> str | None:
    """Return the value to pass as ``environment`` to ``sentry_sdk.init``.

    Passing ``None`` lets sentry-sdk read ``SENTRY_ENVIRONMENT`` itself and,
    if that is also unset, fall back to ``"production"``. We only apply a
    ``"development"`` fallback when Django is running in DEBUG mode, so a
    developer who exports ``SENTRY_DSN`` locally without also setting
    ``SENTRY_ENVIRONMENT`` does not ship events tagged ``"production"`` into
    real production alert rules.
    """
    explicit = os.environ.get("SENTRY_ENVIRONMENT")
    if explicit:
        return explicit
    if debug:
        return "development"
    return None


def should_warn_missing_dsn(dsn: str | None, *, debug: bool) -> bool:
    """Return ``True`` when the missing-DSN startup warning should fire.

    Suppressed when a DSN is set, when Django is in DEBUG mode (dev
    workflows opt out of error reporting on purpose), and when pytest is
    the process driver (tests import settings and would otherwise emit the
    warning at every collection).
    """
    if dsn or debug:
        return False
    if "pytest" in sys.modules:
        return False
    return True


# How long one repeating outage notice stands for. A broker that is down keeps
# producing the same line every second from every consumer thread, so the first
# one is the alert and the rest are the same alert again, in the tens of
# thousands over a long enough outage. Five minutes is short enough that a
# fresh outage after a recovery is still reported promptly.
_OUTAGE_REPORT_INTERVAL_SECONDS = 300

# Logs that a healthy system produces while it recovers on its own. Each entry
# is (logger prefix, substring of the message).
#
# Dramatiq's consumer restarts itself once a second for as long as the broker is
# unreachable, logging at CRITICAL each time — the reconnect loop working, not a
# fault. The first line says the broker is gone, which is worth an alert; the
# thousands behind it say nothing the first one did not.
#
# django-redis writes the second one, at error level, for each failure the
# default cache alias deliberately swallows. That alias exists so an unreachable
# Redis costs a page its cached fragments rather than costing the user the page,
# and DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS is on so the outage is visible at all —
# but every cache read on every request in flight writes one, which is the same
# alert once per request. Throttling keeps the visibility and drops the volume.
#
# Only the alias that swallows is listed. The throttle alias re-raises on
# purpose, so its failures are a decision the app made about a request and are
# reported every time.
_SELF_HEALING_NOTICES = (
    ("dramatiq.worker.ConsumerThread", "Consumer encountered a connection error"),
    ("sbomify.cache", "Exception ignored"),
)

_last_reported: dict[str, float] = {}
_last_reported_lock = threading.Lock()


def _fault_name(record: logging.LogRecord) -> str:
    """What actually went wrong, as far as the record says.

    django-redis logs the same fixed line — "Exception ignored" — for every
    failure it swallows, so the message alone cannot tell a refused connection
    from a read-only replica after a failover or an "OOM command not allowed".
    Without this, all of them share one throttling window and a genuinely new
    fault arriving during an ongoing outage is dropped rather than reported.

    It raises ``ConnectionInterrupted``, whose ``__cause__`` is the redis error
    and whose ``__str__`` is "Redis {cause type}: {cause message}" — so the
    cause is the informative half and the wrapper is the same every time.
    """
    exc_info = record.exc_info
    if not exc_info or exc_info[1] is None:
        return ""
    exc = exc_info[1]
    return type(exc.__cause__ or exc).__name__


def _self_healing_notice_key(record: logging.LogRecord) -> str | None:
    """The throttling key for a repeating self-healing notice, else ``None``."""
    for logger_prefix, needle in _SELF_HEALING_NOTICES:
        if record.name.startswith(logger_prefix) and needle in record.getMessage():
            # Keyed on the notice, not on the logger: dramatiq names one logger
            # per queue, so keying on the name would let a six-queue worker
            # through six times per window for the one outage they all share.
            #
            # The fault is in the key so that one *kind* of failure is throttled
            # rather than the log line, which is what makes this a volume
            # reduction instead of a filter.
            return f"{logger_prefix}:{needle}:{_fault_name(record)}"
    return None


def throttle_self_healing_notices(event: Any, hint: Any) -> Any:
    """``before_send`` hook: report a recovering outage once, not once a second.

    Returns the event to send it, or ``None`` to drop it. Only the notices
    listed above are ever throttled; everything else is returned untouched, so
    this cannot quietly swallow a real error.
    """
    record = (hint or {}).get("log_record")
    if not isinstance(record, logging.LogRecord):
        return event

    key = _self_healing_notice_key(record)
    if key is None:
        return event

    now = time.monotonic()
    with _last_reported_lock:
        previous = _last_reported.get(key)
        if previous is not None and now - previous < _OUTAGE_REPORT_INTERVAL_SECONDS:
            return None
        _last_reported[key] = now
    return event
