"""One answer to "is this a backing service being unavailable?", for every caller.

Postgres and Redis (Valkey in production) are reached from four places: web
requests, Dramatiq workers, WebSocket consumers and the rate limiter. Each grew
its own idea of what an outage looks like, and each reported it its own way, so
one Valkey restart arrived in Sentry from several of them at once, and a
Postgres failover arrived once per request in flight.

This module is the shared half:

* ``unavailable_backend`` classifies an exception as a Postgres or Redis outage,
  or as neither. Only failures that say "the server could not be reached or went
  away" count. A query that is wrong, a deadlock, a statement timeout, a bad
  password or a Redis ``OOM`` are not outages: they are faults in their own
  right and keep being reported as such.
* ``report_backend_outage`` writes the one log line every caller uses for it.
  That line is part of the self-healing taxonomy in ``sentry_config``, so the
  console keeps the first of each per five-minute window, Sentry gets nothing
  for it, and an outage still failing after a full window raises the
  ``sbomify.resilience`` line that *does* reach Sentry.

The web middleware (``sbomify.apps.core.backend_unavailable``), the Dramatiq
middleware (``sbomify.dramatiq_middleware``) and Sentry's ``before_send`` hook
all decide with ``unavailable_backend``, so they cannot disagree about what an
outage is.

Imports of driver and framework packages are deferred: ``settings.py`` imports
``sentry_config``, which imports this, before Django is configured.
"""

from __future__ import annotations

import logging
from typing import Literal

Backend = Literal["postgres", "redis"]

#: The logger the shared outage line is written on. Listed in
#: ``sentry_config._SELF_HEALING_NOTICES``; renaming it there and not here (or
#: the reverse) would put every outage line back into Sentry one per request.
OUTAGE_LOGGER_NAME = "sbomify.outage"
OUTAGE_MESSAGE_PREFIX = "Backend unavailable"

_logger = logging.getLogger(OUTAGE_LOGGER_NAME)

# SQLSTATEs that mean the server is not serving, rather than that the statement
# was wrong. Class 08 is "connection exception" and is matched by prefix.
#
# 57P01 admin_shutdown, 57P02 crash_shutdown, 57P03 cannot_connect_now (the
# server is starting up or in recovery), 53300 too_many_connections.
_PG_UNAVAILABLE_SQLSTATES = frozenset({"57P01", "57P02", "57P03", "53300"})

# libpq also omits SQLSTATE for authentication, TLS and DSN failures. Only
# recognized transport/availability diagnostics without a code are outages.
_PG_UNAVAILABLE_MESSAGES = (
    "connection refused",
    "connection timed out",
    "timeout expired",
    "could not translate host name",
    "could not resolve hostname",
    "could not receive data from server",
    "could not send data to server",
    "server closed the connection",
    "connection already closed",
    "ssl syscall error",
    "ssl connection has been closed unexpectedly",
    "unexpected eof",
    "network is unreachable",
    "no route to host",
    "database system is starting up",
    "database system is shutting down",
    "database system is in recovery mode",
    "too many clients already",
    "remaining connection slots are reserved",
)

# How far down a ``raise ... from`` chain to look. Django and django-redis each
# add one wrapper; anything deeper is not a wrapped outage.
_MAX_CHAIN = 5


def _classify_one(exc: BaseException) -> Backend | None:
    """The backend ``exc`` itself says is unavailable, without following causes."""
    try:
        import redis.exceptions as redis_exc
    except ImportError:  # pragma: no cover - redis is a hard dependency
        redis_exc = None  # type: ignore[assignment]

    if redis_exc is not None:
        # AuthenticationError and AuthorizationError subclass ConnectionError,
        # but a wrong password does not recover on its own and must stay loud.
        if isinstance(exc, (redis_exc.AuthenticationError, redis_exc.AuthorizationError)):
            return None
        # ConnectionError covers refused, reset, DNS and BusyLoadingError (the
        # server is up but still loading its dataset after a restart).
        if isinstance(exc, (redis_exc.ConnectionError, redis_exc.TimeoutError)):
            return "redis"

    try:
        import dramatiq.errors as dramatiq_errors
    except ImportError:  # pragma: no cover - dramatiq is a hard dependency
        dramatiq_errors = None  # type: ignore[assignment]

    # Dramatiq's own ConnectionError (ConnectionClosed, ConnectionFailed) is not
    # the builtin one; its broker here is Redis, and both raise it ``from None``
    # with the Redis error as the argument, so there is no cause to follow.
    if dramatiq_errors is not None and isinstance(exc, dramatiq_errors.ConnectionError):
        wrapped = exc.args[0] if exc.args else None
        if redis_exc is not None and isinstance(wrapped, (redis_exc.AuthenticationError, redis_exc.AuthorizationError)):
            return None
        return "redis"

    try:
        import psycopg2
    except ImportError:  # pragma: no cover - psycopg2 is a hard dependency
        psycopg2 = None  # type: ignore[assignment]

    if psycopg2 is not None:
        # "connection already closed": the socket was gone before the query.
        if isinstance(exc, psycopg2.InterfaceError):
            return "postgres"
        if isinstance(exc, psycopg2.OperationalError):
            pgcode = getattr(exc, "pgcode", None)
            if pgcode is None:
                diagnostic = str(exc).casefold()
                return "postgres" if any(message in diagnostic for message in _PG_UNAVAILABLE_MESSAGES) else None
            if pgcode.startswith("08") or pgcode in _PG_UNAVAILABLE_SQLSTATES:
                return "postgres"
            return None

    return None


def unavailable_backend(exc: BaseException | None) -> Backend | None:
    """Which backing service ``exc`` says is unreachable, or ``None``.

    Follows ``__cause__`` only, never ``__context__``: Django's
    ``DatabaseError`` wrapper and django-redis's ``ConnectionInterrupted`` both
    raise ``from`` the driver error, which is what is classified. An unrelated
    error raised while *handling* an outage is that unrelated error, and must
    not be filed as the outage.
    """
    for _ in range(_MAX_CHAIN):
        if exc is None:
            return None
        backend = _classify_one(exc)
        if backend is not None:
            return backend
        exc = exc.__cause__
    return None


def report_backend_outage(exc: BaseException, where: str) -> Backend | None:
    """Log the shared outage line for ``exc`` if it is one, and say which backend.

    ``where`` is a short fixed label for the caller ("web request", "task
    sync_integration"), never a path or an id: the line is grouped on, and it
    ships to the log pipeline.

    Returns ``None`` and logs nothing for anything that is not an outage, so a
    caller can hand over every exception it catches.
    """
    backend = unavailable_backend(exc)
    if backend is None:
        return None
    # ERROR so the log pipeline's first-line-of-an-outage alert still sees it;
    # the self-healing throttle keeps it to one line per fault per window, and
    # ``before_send`` keeps it out of Sentry.
    _logger.error(
        "%s: %s (%s) during %s",
        OUTAGE_MESSAGE_PREFIX,
        backend,
        type(exc.__cause__ or exc).__name__,
        where,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return backend
