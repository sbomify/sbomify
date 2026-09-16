"""Pure helpers for Sentry startup wiring and self-healing-notice throttling.

Extracted from ``settings.py`` so regression tests can pin the actual
resolution logic instead of duplicating it locally.

The throttle below started as a Sentry ``before_send`` hook and now serves the
log stream as well; it lives here rather than in ``logging_filters`` because
what it needs is the fault taxonomy at the bottom of this module, not the
filter plumbing.
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

# Keys are namespaced by consumer ("sentry:…", "log:…"). Sentry and the log
# handler are different consumers of the same taxonomy and must not share a
# window: a filter on the console handler cannot see what Sentry decided, and a
# shared window would mean whichever one asked first spent the other's report.
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


# Where the "this one did not recover" signal goes. Deliberately its own logger,
# outside the taxonomy above: it must never be throttled by the machinery that
# produced it, and Graylog alerts on it by name.
_SUSTAINED_LOGGER = logging.getLogger("sbomify.resilience")

# A report whose predecessor is older than two windows opens a new episode
# rather than continuing one. Production's dramatiq consumers drop their Redis
# connection on a ~15.5-hour cycle and recover within the same second; without
# this bound, the next cycle would read as the same outage still running half a
# day later.
_EPISODE_CONTINUES_WITHIN_SECONDS = 2 * _OUTAGE_REPORT_INTERVAL_SECONDS


def _open_window(key: str) -> tuple[bool, bool]:
    """``(report, still_failing)`` for one fault.

    ``report`` is ``False`` while the window opened by the last report is still
    running. ``still_failing`` says the last report was recent enough that the
    fault never stopped in between, so it has now outlived a full window.
    """
    now = time.monotonic()
    with _last_reported_lock:
        previous = _last_reported.get(key)
        if previous is not None and now - previous < _OUTAGE_REPORT_INTERVAL_SECONDS:
            return False, False
        _last_reported[key] = now
    return True, previous is not None and now - previous < _EPISODE_CONTINUES_WITHIN_SECONDS


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

    report, _ = _open_window(f"sentry:{key}")
    return event if report else None


def is_repeat_self_healing_notice(record: logging.LogRecord) -> bool:
    """``True`` for a self-healing notice already written inside this window.

    The same throttle as the Sentry hook, applied to stdout, because stdout is
    where the on-call signal actually comes from: the container logs ship to
    Graylog and Graylog alerts Slack on error-level volume. Throttling only the
    Sentry copy left that path seeing every line, so one Redis blip — one fault,
    self-healing, already recovered by the time anyone looked — arrived as
    hundreds of error-level lines and cleared the alert threshold on its own.

    Keeping the first line of each fault per window is what makes this safe to
    put on a handler: an outage that lasts is still reported, once every five
    minutes, for as long as it lasts.

    Opening a window is also where a fault is found to have *not* recovered, so
    that is where the sustained-fault signal is raised. Nothing else in the
    process knows: a log line says a fault happened, and only the gap between
    two of them says it is still happening.
    """
    # Both notices are logged at ERROR or above, so this skips formatting the
    # message for the INFO/WARNING records that make up the bulk of the stream.
    if record.levelno < logging.ERROR:
        return False

    key = _self_healing_notice_key(record)
    if key is None:
        return False

    report, still_failing = _open_window(f"log:{key}")
    if still_failing:
        _raise_sustained_fault(key)
    return not report


def _raise_sustained_fault(key: str) -> None:
    """Log the one line that means *this did not recover*.

    Why a separate line rather than counting the throttled notices: the throttle
    window is per process, and there is no shared state to make it otherwise -
    the fault being throttled is "Redis is unreachable", so a Redis-backed lock
    is exactly the thing that cannot be relied on here. Production runs two web
    containers with two gunicorn workers each plus two dramatiq workers, so a
    blip lasting under a second still produces one "first line" from every
    process that saw it. Counting lines therefore cannot tell six processes
    noticing one blip apart from one process seeing six windows of a real
    outage, unless the threshold hardcodes the replica count.

    Duration can tell them apart, and each process can measure it alone. Replayed
    over a week of production this is silent through all ten reconnect blips and
    raises seven lines during the one real Redis incident, which is the whole
    point: the alert on it needs no threshold at all.
    """
    _SUSTAINED_LOGGER.error(
        "Dependency still failing %d minutes after the first report: %s",
        _OUTAGE_REPORT_INTERVAL_SECONDS // 60,
        key,
    )
