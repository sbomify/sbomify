"""What the app does when its backing services misbehave, and what it reports.

Four defects sat together in the error tracker, and they are the same defect
seen from different sides: something outside the request went wrong, and the app
turned it into either a page the user could not use or an alert nobody could act
on.

* The task broker's client was built so that every resilience setting written
  for it was silently discarded on any deployment not using TLS.
* Nothing was configured to retry a dropped Redis connection, so the channel
  layer and the broker re-raised the first refused socket at their caller.
* A WebSocket to a path this app does not serve raised out of the ASGI
  application, so scanners produced tracebacks that read as our fault.
* Dramatiq's consumer reconnects once a second while the broker is down, and
  logs at CRITICAL each time. One outage arrived as 21,512 alerts.

Each is pinned here because none of them is visible from ordinary use: they only
show up when Redis is already having a bad day, which is exactly when nobody
wants to be reading a settings diff.
"""

from __future__ import annotations

import logging

import pytest
from redis.asyncio.retry import Retry as AsyncRedisRetry
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from redis.retry import Retry as RedisRetry

from sbomify.sentry_config import (
    _OUTAGE_REPORT_INTERVAL_SECONDS,
    _last_reported,
    throttle_self_healing_notices,
)
from sbomify.settings import (
    apply_db_resilience,
    build_dramatiq_redis_options,
    build_redis_client_kwargs,
)

# ``test_settings`` swaps the broker for a stub and the database for SQLite, so
# reading ``django.conf.settings`` here would pin the test rig rather than the
# thing being fixed. These call the same builders ``settings.py`` calls, the way
# ``test_cache_outage`` does with ``build_redis_caches``.
_REDIS = "redis://localhost:6379/1"

# Every kwarg the resilience block exists to deliver. Named here so a setting
# added there without being delivered anywhere fails this test.
RESILIENCE_KWARGS = ("socket_keepalive", "health_check_interval", "socket_connect_timeout")


def test_broker_client_actually_receives_the_resilience_settings() -> None:
    """The defect: ``RedisBroker(url=...)`` throws these away.

    Given ``url``, the broker builds its pool with ``ConnectionPool.from_url(url)``
    — no extra kwargs — and hands the rest to ``redis.Redis(**parameters)``,
    which ignores per-connection kwargs whenever a pool is supplied. So the
    keepalive, the health check and the connect timeout reached nothing on any
    deployment without TLS. Only the TLS branch, which passes a pre-built
    client, ever had them.

    Asserted against the pool the broker will really use, not against the
    options dict, because the options dict looked correct the whole time.
    """
    client = build_dramatiq_redis_options(_REDIS)["client"]
    connection_kwargs = client.connection_pool.connection_kwargs

    for kwarg in RESILIENCE_KWARGS:
        assert connection_kwargs.get(kwarg) is not None, f"{kwarg} never reached the broker's connections"


@pytest.mark.parametrize(
    ("label", "asyncio", "retry_class"),
    [
        ("channel layer", True, AsyncRedisRetry),
        ("task broker", False, RedisRetry),
    ],
)
def test_a_dropped_redis_connection_is_retried(label, asyncio, retry_class) -> None:
    """redis-py retries nothing by default, and nothing asked it to.

    ``Retry(NoBackoff(), 0)`` is the default, so a broker restart surfaced as a
    failure per in-flight operation when waiting a moment and reconnecting would
    have served all of them.

    The retry class matters as much as the retry: the channel layer is async and
    the sync ``call_with_retry`` is not awaitable, so sharing one object between
    the two would break the channel layer on its first retry rather than on none
    — a worse failure than the one being fixed, and invisible until an outage.
    """
    connection_kwargs = build_redis_client_kwargs(asyncio=asyncio)
    retry = connection_kwargs.get("retry")
    assert retry is not None, f"{label} has no retry policy"
    assert isinstance(retry, retry_class), f"{label} needs a {retry_class.__name__}"
    assert retry.get_retries() > 0, f"{label} has a retry policy that never retries"

    retry_on_error = connection_kwargs.get("retry_on_error") or []
    assert RedisConnectionError in retry_on_error
    assert RedisTimeoutError in retry_on_error


def test_the_database_replaces_a_connection_that_died_between_requests() -> None:
    """Persistent connections are only safe with the health check on.

    ``CONN_MAX_AGE`` is left to the environment — how many connections Postgres
    can afford is an operational question — but whenever it is raised, a
    connection reused across a restart or a failover must be pinged and replaced
    rather than handed to a view. Keepalives cover the other half: a connection
    killed on the far side is detected instead of blocking on a read that will
    never return.
    """
    config = apply_db_resilience({"ENGINE": "django.db.backends.postgresql"})
    assert config["CONN_HEALTH_CHECKS"] is True

    options = config["OPTIONS"]
    assert options["keepalives"] == 1
    assert options["connect_timeout"] > 0


def test_db_resilience_does_not_overwrite_what_the_environment_set() -> None:
    """A deployment that already tuned an option keeps its value.

    The TLS options are set on the same dict a few lines earlier, so blindly
    assigning would have been a way to drop ``sslmode`` on the floor.
    """
    config = apply_db_resilience(
        {
            "ENGINE": "django.db.backends.postgresql",
            "OPTIONS": {"sslmode": "verify-full", "connect_timeout": 3},
        }
    )
    assert config["OPTIONS"]["sslmode"] == "verify-full"
    assert config["OPTIONS"]["connect_timeout"] == 3


@pytest.mark.parametrize(
    "engine",
    ["django.db.backends.sqlite3", "django.db.backends.mysql", "django.db.backends.oracle"],
)
def test_libpq_options_are_not_forced_on_other_backends(engine: str) -> None:
    """These options are libpq keywords, passed to the driver verbatim.

    ``DATABASE_URL`` is parsed by dj_database_url, which resolves ``sqlite://``
    and ``mysql://`` as happily as ``postgres://``, so the engine cannot be
    assumed. sqlite3 answers ``connect_timeout`` with ``TypeError: invalid
    keyword argument`` — and on the first query rather than at startup, so it
    would look like a runtime fault rather than a misconfiguration.

    The two Django-level settings still apply: they are backend-agnostic.
    """
    config = apply_db_resilience({"ENGINE": engine})

    assert config.get("OPTIONS", {}) == {}
    assert config["CONN_HEALTH_CHECKS"] is True
    assert "CONN_MAX_AGE" in config


class _Record(logging.LogRecord):
    """A log record with a name, a message and optionally the exception.

    ``exc_info`` matters for the django-redis case: that logger writes one fixed
    line for every failure it swallows, so the exception is the only thing that
    says which failure it was.
    """

    def __init__(self, name: str, message: str, exc: BaseException | None = None) -> None:
        exc_info = (type(exc), exc, None) if exc is not None else None
        super().__init__(name, logging.CRITICAL, __file__, 1, message, None, exc_info)


# The line dramatiq's reconnect loop emits, and the two queues a worker runs it
# from. Named because they appear inside call arguments below.
_LOOP = "Consumer encountered a connection error: x"
_PLUGINS = "dramatiq.worker.ConsumerThread(plugins)"
_BILLING = "dramatiq.worker.ConsumerThread(billing)"


@pytest.fixture(autouse=True)
def _forget_throttled_notices():
    """The hook's window is process-wide; tests must not inherit each other's."""
    _last_reported.clear()
    yield
    _last_reported.clear()


def test_one_outage_reports_once_however_many_queues_notice_it() -> None:
    """The symptom: 21,512 events for a single Redis window.

    Dramatiq restarts its consumer once a second for as long as the broker is
    unreachable, and logs at CRITICAL each time — one logger per queue, so a
    six-queue worker multiplies it again. That is the reconnect loop working.
    The first line is the alert; the rest are the same alert.

    Keyed on the notice rather than the logger name for that reason: keying on
    the name would let one outage through once per queue.
    """
    first = throttle_self_healing_notices({"event": 1}, {"log_record": _Record(_PLUGINS, _LOOP)})
    assert first is not None, "the first notice of an outage must still be reported"

    repeat_same_queue = throttle_self_healing_notices({"event": 2}, {"log_record": _Record(_PLUGINS, _LOOP)})
    repeat_other_queue = throttle_self_healing_notices({"event": 3}, {"log_record": _Record(_BILLING, _LOOP)})
    assert repeat_same_queue is None
    assert repeat_other_queue is None


def test_the_cache_reports_a_swallowed_outage_once_not_once_per_request() -> None:
    """The same shape one layer up, from django-redis.

    Every failure the default cache alias swallows is logged at error level, on
    purpose, so an outage is visible rather than showing up only as latency. But
    it is written per cache read per request in flight — the alias is doing
    exactly what it was configured to do, once per page, and each one arrived as
    its own alert.
    """
    swallowed = _Record("sbomify.cache", "Exception ignored")

    assert throttle_self_healing_notices({"event": 1}, {"log_record": swallowed}) is not None
    assert throttle_self_healing_notices({"event": 2}, {"log_record": swallowed}) is None


def test_a_different_redis_fault_is_reported_even_mid_outage() -> None:
    """Throttling one failure must not hide a second, different one.

    django-redis logs the same fixed line whatever went wrong, so keying on the
    message alone puts a refused connection, a read-only replica after a
    failover and an "OOM command not allowed" into one five-minute bucket. The
    second and third would then be dropped for as long as the first kept
    happening — which is exactly when a new fault most needs reporting.
    """
    from redis.exceptions import ConnectionError as RedisConnError
    from redis.exceptions import ResponseError

    def swallowed(cause: BaseException) -> _Record:
        # django-redis raises ConnectionInterrupted *from* the redis error, so
        # the cause is the informative half; the wrapper is identical every time.
        wrapper = Exception("ConnectionInterrupted")
        wrapper.__cause__ = cause
        return _Record("sbomify.cache", "Exception ignored", wrapper)

    refused = swallowed(RedisConnError("Error 111 connecting to redis"))
    assert throttle_self_healing_notices({"event": 1}, {"log_record": refused}) is not None
    assert throttle_self_healing_notices({"event": 2}, {"log_record": refused}) is None

    oom = swallowed(ResponseError("OOM command not allowed when used memory > 'maxmemory'"))
    assert throttle_self_healing_notices({"event": 3}, {"log_record": oom}) is not None


def test_the_throttle_alias_failing_is_never_throttled() -> None:
    """The alias that re-raises is a decision about a request, not a recovery.

    The default alias swallows and reports; the throttle alias refuses the call,
    because a swallowed read looks like an empty window and hands every caller a
    fresh budget exactly when Redis is unwell. Those refusals are per-request
    facts and every one of them should be reported.

    It rides in on the same logger, so this is the case that says the message,
    not just the logger, has to match.
    """
    refused = _Record("sbomify.cache", "ConnectionInterrupted: Redis TimeoutError")

    assert throttle_self_healing_notices({"event": 1}, {"log_record": refused}) is not None
    assert throttle_self_healing_notices({"event": 2}, {"log_record": refused}) is not None


def test_a_later_outage_is_reported_again() -> None:
    """Throttling must not turn into silence.

    A window that never reopens would report the first outage after a deploy and
    nothing ever again, which is worse than the noise it replaced.
    """
    record = _Record(_PLUGINS, _LOOP)
    assert throttle_self_healing_notices({"event": 1}, {"log_record": record}) is not None
    assert throttle_self_healing_notices({"event": 2}, {"log_record": record}) is None

    # Rewind the window rather than sleeping through it.
    for key in _last_reported:
        _last_reported[key] -= _OUTAGE_REPORT_INTERVAL_SECONDS + 1

    assert throttle_self_healing_notices({"event": 3}, {"log_record": record}) is not None


@pytest.mark.parametrize(
    "hint",
    [
        None,
        {},
        {"log_record": _Record("sbomify.apps.core", _LOOP)},
        {"log_record": _Record(_PLUGINS, "Consumer encountered an unexpected error.")},
    ],
    ids=["no hint", "empty hint", "our own logger", "the other consumer failure"],
)
def test_nothing_else_is_ever_dropped(hint) -> None:
    """The hook must be incapable of swallowing a real error.

    The last case is the one worth naming: dramatiq's ``except Exception``
    branch logs from the same logger at the same level, and it is a genuine
    fault. Matching on the logger alone would have hidden it.
    """
    assert throttle_self_healing_notices({"event": 1}, hint) is not None
