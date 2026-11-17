"""One definition of "Postgres or Redis is unreachable", and everything built on it.

The outage classifier decides what the web middleware answers with 503, what
the task middleware and the rate limiter report through the shared outage line,
what the console stops printing a traceback for, and what Sentry drops. So the
cases worth pinning are mostly the ones it must *not* match: a deadlock, a bad
password, an OOM, or an unrelated error raised while handling an outage are
faults in their own right and must keep reaching whoever reads them.
"""

from __future__ import annotations

import logging
import os
import socket
from types import SimpleNamespace
from typing import Any

import psycopg2
import pytest
from django.db import InterfaceError as DjangoInterfaceError
from django.db import OperationalError as DjangoOperationalError
from django.http import HttpRequest, HttpResponse
from django.urls import path
from django_redis.exceptions import ConnectionInterrupted
from dramatiq.errors import ConnectionClosed, ConnectionFailed
from redis.exceptions import AuthenticationError, AuthorizationError, BusyLoadingError, ResponseError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from sbomify import sentry_config
from sbomify.apps.core.backend_unavailable import RETRY_AFTER_SECONDS
from sbomify.backend_outage import OUTAGE_LOGGER_NAME, report_backend_outage, unavailable_backend
from sbomify.dramatiq_middleware import BackendOutageMiddleware
from sbomify.logging_filters import is_backend_outage_traceback
from sbomify.sentry_config import _last_reported, throttle_self_healing_notices


def _wrapped(outer: BaseException, cause: BaseException) -> BaseException:
    """``outer`` raised ``from cause``, the way Django and django-redis wrap."""
    outer.__cause__ = cause
    return outer


class _PgWithCode(psycopg2.OperationalError):
    """A server-reported psycopg2 error; the real ``pgcode`` is set only by libpq."""

    pgcode = "40P01"


class _PgShuttingDown(psycopg2.OperationalError):
    pgcode = "57P01"


def _context_only() -> BaseException:
    """A ValueError raised while handling a Redis outage, not caused by it."""
    try:
        try:
            raise RedisConnectionError("Error 111")
        except RedisConnectionError:
            raise ValueError("unrelated")
    except ValueError as exc:
        return exc


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RedisConnectionError("Error 111 connecting to redis:6379. Connection refused."), "redis"),
        (RedisTimeoutError("Timeout reading from socket"), "redis"),
        (BusyLoadingError("Redis is loading the dataset in memory"), "redis"),
        (ConnectionClosed(RedisConnectionError("x")), "redis"),
        (_wrapped(ConnectionInterrupted(connection=None), RedisConnectionError("x")), "redis"),
        (_wrapped(DjangoOperationalError("x"), psycopg2.OperationalError("server closed the connection")), "postgres"),
        (_wrapped(DjangoOperationalError("x"), _PgShuttingDown("terminating connection")), "postgres"),
        (_wrapped(DjangoInterfaceError("x"), psycopg2.InterfaceError("connection already closed")), "postgres"),
        # Not outages.
        (AuthenticationError("invalid password"), None),
        (_wrapped(ConnectionInterrupted(connection=None), ResponseError("OOM command not allowed")), None),
        (_wrapped(DjangoOperationalError("x"), _PgWithCode("deadlock detected")), None),
        (DjangoOperationalError('near "[]": syntax error'), None),
        (_context_only(), None),
        (ValueError("x"), None),
        (None, None),
    ],
    ids=[
        "redis refused",
        "redis timeout",
        "redis loading after restart",
        "dramatiq broker connection",
        "django-redis wrapper",
        "postgres connection lost",
        "postgres shutting down",
        "postgres connection closed",
        "redis bad password",
        "redis oom",
        "postgres deadlock",
        "sqlite operational error",
        "unrelated error while handling an outage",
        "plain error",
        "nothing",
    ],
)
def test_what_counts_as_an_outage(exc: BaseException | None, expected: str | None) -> None:
    assert unavailable_backend(exc) == expected


@pytest.mark.parametrize(
    "diagnostic",
    [
        'connection to server at "db" failed: FATAL: password authentication failed for user "app"',
        'connection to server at "db" failed: fe_sendauth: no password supplied',
        'connection to server at "db" failed: FATAL: no pg_hba.conf entry for host "192.0.2.1"',
        'connection to server at "db" failed: FATAL: database "missing" does not exist',
        'connection to server at "db" failed: SSL error: certificate verify failed',
        'invalid dsn: invalid connection option "unknown"',
    ],
)
def test_postgres_configuration_failures_without_sqlstate_stay_reported(diagnostic: str) -> None:
    driver_error = psycopg2.OperationalError(diagnostic)
    assert driver_error.pgcode is None
    exc = _wrapped(DjangoOperationalError(diagnostic), driver_error)

    assert unavailable_backend(exc) is None
    assert throttle_self_healing_notices({"e": 1}, _hint(exc)) is not None


@pytest.mark.parametrize(
    "diagnostic",
    [
        "connection refused",
        "connection timed out",
        "timeout expired",
        'could not translate host name "db" to address: Temporary failure in name resolution',
        "server closed the connection unexpectedly",
        "SSL SYSCALL error: Connection reset by peer",
        "SSL connection has been closed unexpectedly",
        "FATAL: the database system is starting up",
        "FATAL: sorry, too many clients already",
    ],
)
def test_postgres_transport_failures_without_sqlstate_are_outages(diagnostic: str) -> None:
    assert unavailable_backend(psycopg2.OperationalError(diagnostic)) == "postgres"


@pytest.mark.parametrize("wrapper", [ConnectionClosed, ConnectionFailed])
@pytest.mark.parametrize("driver_error", [AuthenticationError, AuthorizationError])
def test_dramatiq_authentication_failures_stay_reported(
    wrapper: type[ConnectionClosed] | type[ConnectionFailed],
    driver_error: type[AuthenticationError] | type[AuthorizationError],
) -> None:
    exc = wrapper(driver_error("invalid credentials"))

    assert unavailable_backend(exc) is None
    assert throttle_self_healing_notices({"e": 1}, _hint(exc)) is not None


def test_consumer_auth_failure_reports_even_during_a_connection_outage() -> None:
    def notice(exc: BaseException) -> logging.LogRecord:
        return logging.LogRecord(
            "dramatiq.worker.ConsumerThread(default)",
            logging.CRITICAL,
            __file__,
            1,
            "Consumer encountered a connection error: %s",
            (ConnectionClosed(exc),),
            None,
        )

    outage = notice(RedisConnectionError("connection refused"))
    auth = notice(AuthenticationError("invalid credentials"))
    assert throttle_self_healing_notices({"e": 1}, {"log_record": outage}) is None
    assert sentry_config.is_repeat_self_healing_notice(outage) is False

    # A different fault must not spend the authentication failure's window.
    assert throttle_self_healing_notices({"e": 2}, {"log_record": auth}) is not None
    assert sentry_config.is_repeat_self_healing_notice(auth) is False
    assert throttle_self_healing_notices({"e": 3}, {"log_record": auth}) is None
    assert sentry_config.is_repeat_self_healing_notice(auth) is True


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def outage_lines():
    """Lines written on the shared outage logger (``sbomify`` does not propagate)."""
    capture = _Capture()
    logger = logging.getLogger(OUTAGE_LOGGER_NAME)
    logger.addHandler(capture)
    try:
        yield capture.records
    finally:
        logger.removeHandler(capture)


@pytest.fixture(autouse=True)
def _forget_throttled_notices():
    _last_reported.clear()
    yield
    _last_reported.clear()


def test_the_outage_line_names_the_backend_and_feeds_the_throttle(outage_lines) -> None:
    """The line is part of the self-healing taxonomy, so the console keeps one
    per window and an outage that lasts raises the sustained-fault line."""
    assert report_backend_outage(RedisConnectionError("Error 111"), "task x") == "redis"
    assert report_backend_outage(ValueError("x"), "task x") is None

    assert len(outage_lines) == 1
    line = outage_lines[0]
    assert line.levelno == logging.ERROR
    assert "redis" in line.getMessage() and "task x" in line.getMessage()
    assert sentry_config._self_healing_notice_key(line) is not None
    # Writing it went through the console filter, which opened the window.
    _last_reported.clear()
    assert sentry_config.is_repeat_self_healing_notice(line) is False
    assert sentry_config.is_repeat_self_healing_notice(line) is True


# --- Web requests -----------------------------------------------------------


def _postgres_down(request: HttpRequest) -> HttpResponse:
    raise _wrapped(DjangoOperationalError("x"), psycopg2.OperationalError("connection refused"))


def _redis_down(request: HttpRequest) -> HttpResponse:
    raise RedisConnectionError("Error 111 connecting to redis:6379. Connection refused.")


def _postgres_bad_password(request: HttpRequest) -> HttpResponse:
    diagnostic = 'FATAL: password authentication failed for user "app"'
    raise _wrapped(DjangoOperationalError(diagnostic), psycopg2.OperationalError(diagnostic))


def _broken(request: HttpRequest) -> HttpResponse:
    raise ValueError("a bug")


urlpatterns = [
    path("pg/", _postgres_down),
    path("api/v1/redis/", _redis_down),
    path("pg-bad-password/", _postgres_bad_password),
    path("broken/", _broken),
]


@pytest.mark.django_db
@pytest.mark.urls(__name__)
class TestWebRequests:
    @pytest.fixture
    def client(self, client):
        client.raise_request_exception = False
        return client

    def test_an_unreachable_database_is_a_503_the_client_can_retry(self, client, outage_lines) -> None:
        response = client.get("/pg/")

        assert response.status_code == 503
        assert response["Retry-After"] == str(RETRY_AFTER_SECONDS)
        assert response["Cache-Control"] == "no-store"
        assert len(outage_lines) == 1
        assert "postgres" in outage_lines[0].getMessage()

    def test_an_api_caller_gets_json(self, client) -> None:
        response = client.get("/api/v1/redis/")

        assert response.status_code == 503
        assert response.json() == {"detail": "The service is temporarily unavailable. Please try again in a moment."}

    def test_a_bug_is_still_a_500(self, client, outage_lines) -> None:
        response = client.get("/broken/")

        assert response.status_code == 500
        assert outage_lines == []

    def test_bad_database_credentials_are_not_a_retryable_outage(self, client, outage_lines) -> None:
        response = client.get("/pg-bad-password/")

        assert response.status_code == 500
        assert "Retry-After" not in response
        assert outage_lines == []

    def test_an_outage_raised_in_middleware_is_a_503_too(self, client, mocker, outage_lines) -> None:
        """The session and custom-domain lookups run in middleware, before any
        view: Django has already turned the exception into a 500 by the time an
        outer layer sees it, which is why the cause is carried on the request."""
        mocker.patch(
            "sbomify.apps.core.middleware.RealIPMiddleware.__call__",
            side_effect=_wrapped(DjangoOperationalError("x"), psycopg2.OperationalError("connection refused")),
        )

        response = client.get("/broken/")

        assert response.status_code == 503
        assert outage_lines

    def test_the_503_is_not_logged_again_per_request(self, client, outage_lines) -> None:
        """The outage line reported it; Django would otherwise add a
        "Service Unavailable" error line for every request in flight."""
        capture = _Capture()
        logger = logging.getLogger("django.request")
        logger.addHandler(capture)
        try:
            client.get("/pg/")
        finally:
            logger.removeHandler(capture)

        assert [r.getMessage() for r in capture.records if r.levelno >= logging.ERROR and r.exc_info is None] == []


def test_the_tea_api_lets_an_outage_reach_the_middleware() -> None:
    """TEA catches every exception into a 500; an outage must become a 503."""
    from sbomify.apps.tea.urls import tea_global_exception_handler

    with pytest.raises(RedisConnectionError):
        tea_global_exception_handler(HttpRequest(), RedisConnectionError("down"))


# --- Tasks ------------------------------------------------------------------


class _Message:
    actor_name = "sync_integration"


def test_a_task_failing_on_an_outage_writes_the_outage_line(outage_lines) -> None:
    middleware = BackendOutageMiddleware()

    middleware.after_process_message(None, _Message(), exception=RedisTimeoutError("x"))  # type: ignore[arg-type]
    middleware.after_process_message(None, _Message(), exception=ValueError("x"))  # type: ignore[arg-type]
    middleware.after_process_message(None, _Message(), result=None)  # type: ignore[arg-type]

    assert len(outage_lines) == 1
    assert "task sync_integration" in outage_lines[0].getMessage()


# --- Sentry -----------------------------------------------------------------


def _hint(exc: BaseException) -> dict[str, Any]:
    return {"exc_info": (type(exc), exc, None)}


def _in_task(retries: int) -> dict[str, Any]:
    return {"contexts": {"dramatiq": {"data": {"actor_name": "sync_integration", "options": {"retries": retries}}}}}


def test_sentry_drops_a_request_failing_on_an_outage() -> None:
    assert throttle_self_healing_notices({"e": 1}, _hint(RedisConnectionError("x"))) is None


def test_sentry_keeps_a_real_error() -> None:
    assert throttle_self_healing_notices({"e": 1}, _hint(ValueError("x"))) is not None


def test_sentry_drops_a_task_attempt_that_will_be_retried(mocker) -> None:
    mocker.patch.object(sentry_config, "_actor_max_retries", return_value=3)

    assert throttle_self_healing_notices(_in_task(retries=1), _hint(RedisConnectionError("x"))) is None


def test_sentry_keeps_the_attempt_that_loses_the_message(mocker) -> None:
    """Out of retries, the message is gone: that is news whatever the cause."""
    mocker.patch.object(sentry_config, "_actor_max_retries", return_value=3)

    assert throttle_self_healing_notices(_in_task(retries=4), _hint(RedisConnectionError("x"))) is not None


def test_sentry_keeps_a_task_attempt_whose_retry_count_cannot_be_read(mocker) -> None:
    mocker.patch.object(sentry_config, "_actor_max_retries", return_value=None)

    assert throttle_self_healing_notices(_in_task(retries=1), _hint(RedisConnectionError("x"))) is not None


def test_sentry_drops_the_outage_line_but_keeps_the_sustained_one() -> None:
    outage = logging.LogRecord(OUTAGE_LOGGER_NAME, logging.ERROR, __file__, 1, "Backend unavailable: redis", None, None)
    outage.exc_info = (RedisConnectionError, RedisConnectionError("x"), None)
    sustained = logging.LogRecord(
        "sbomify.resilience", logging.ERROR, __file__, 1, "Dependency still failing 5 minutes after", None, None
    )

    assert throttle_self_healing_notices({"e": 1}, {"log_record": outage}) is None
    assert throttle_self_healing_notices({"e": 2}, {"log_record": sustained}) is not None


# --- Console ----------------------------------------------------------------


def _record(name: str, level: int, exc: BaseException | None) -> logging.LogRecord:
    exc_info = (type(exc), exc, None) if exc is not None else None
    return logging.LogRecord(name, level, __file__, 1, "Internal Server Error: /", None, exc_info)


@pytest.mark.parametrize(
    ("record", "dropped"),
    [
        (_record("django.request", logging.ERROR, RedisConnectionError("x")), True),
        (_record("dramatiq.worker.WorkerThread", logging.ERROR, RedisConnectionError("x")), True),
        (_record("django.request", logging.ERROR, ValueError("x")), False),
        (_record("django.request", logging.ERROR, None), False),
        (_record("django.request", logging.WARNING, RedisConnectionError("x")), False),
        (_record("sbomify.apps.core", logging.ERROR, RedisConnectionError("x")), False),
    ],
    ids=["request outage", "task outage", "request bug", "no traceback", "warning", "our own logger"],
)
def test_the_console_drops_only_per_failure_outage_tracebacks(record: logging.LogRecord, dropped: bool) -> None:
    assert is_backend_outage_traceback(record) is dropped


# --- What the services actually raise -----------------------------------------
# The cases above build their exceptions by hand. These provoke them: a port
# nothing listens on, Django's and django-redis's real wrappers, the test server
# refusing a login, a statement timeout and a terminated session.


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _postgres(**overrides: Any) -> Any:
    from django.db import connection
    from django.db.backends.postgresql.base import DatabaseWrapper

    settings_dict = {**connection.settings_dict, **overrides}
    settings_dict["OPTIONS"] = {**settings_dict.get("OPTIONS", {}), "connect_timeout": 2}
    return DatabaseWrapper(settings_dict, alias="outage-probe")


@pytest.mark.django_db
def test_a_postgres_server_that_refuses_the_connection_is_an_outage() -> None:
    probe = _postgres(HOST="127.0.0.1", PORT=str(_closed_port()))

    with pytest.raises(DjangoOperationalError) as caught:
        probe.ensure_connection()

    assert unavailable_backend(caught.value) == "postgres"


@pytest.mark.django_db
@pytest.mark.parametrize("overrides", [{"PASSWORD": "not-the-password"}, {"NAME": "sbomify_no_such_database"}])
def test_a_postgres_server_that_rejects_the_login_is_not_an_outage(overrides: dict[str, str]) -> None:
    probe = _postgres(**overrides)

    with pytest.raises(DjangoOperationalError) as caught:
        probe.ensure_connection()

    assert unavailable_backend(caught.value) is None


@pytest.mark.django_db
def test_a_statement_timeout_is_not_an_outage() -> None:
    from django.db import connection, transaction

    with pytest.raises(DjangoOperationalError) as caught, transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = 1")
        cursor.execute("SELECT pg_sleep(1)")

    assert unavailable_backend(caught.value) is None


@pytest.mark.django_db
def test_a_terminated_postgres_session_is_an_outage() -> None:
    from django.db import connection

    victim = _postgres()
    victim.ensure_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_terminate_backend(%s)", [victim.connection.get_backend_pid()])
        with pytest.raises((DjangoOperationalError, DjangoInterfaceError)) as caught, victim.cursor() as cursor:
            cursor.execute("SELECT 1")
    finally:
        victim.close()

    assert unavailable_backend(caught.value) == "postgres"


def test_a_redis_server_that_refuses_the_connection_is_an_outage() -> None:
    import redis
    from django_redis.cache import RedisCache

    port = _closed_port()
    cache = RedisCache(f"redis://127.0.0.1:{port}/0", {"OPTIONS": {"SOCKET_CONNECT_TIMEOUT": 1}})
    with pytest.raises(RedisConnectionError) as refused:
        redis.Redis(host="127.0.0.1", port=port, socket_connect_timeout=1).ping()
    # django-redis's client raises its wrapper, and the cache API re-raises the cause.
    with pytest.raises(ConnectionInterrupted) as wrapped:
        cache.client.get("key")
    with pytest.raises(RedisConnectionError) as unwrapped:
        cache.get("key")

    assert unavailable_backend(refused.value) == "redis"
    assert unavailable_backend(wrapped.value) == "redis"
    assert unavailable_backend(unwrapped.value) == "redis"


def test_a_redis_server_that_rejects_the_password_is_not_an_outage() -> None:
    import redis

    location = os.environ.get("REDIS_URL")
    if not location:
        pytest.skip("needs a Redis server to log in to")
    with pytest.raises(AuthenticationError) as caught:
        redis.Redis.from_url(location, password="not-the-password", socket_connect_timeout=1).ping()

    assert unavailable_backend(caught.value) is None


def test_a_dramatiq_consumer_losing_redis_is_an_outage() -> None:
    from dramatiq.brokers.redis import RedisBroker

    consumer = RedisBroker(url=f"redis://127.0.0.1:{_closed_port()}/0", socket_connect_timeout=1).consume("default")

    with pytest.raises(ConnectionClosed) as caught:
        next(consumer)

    assert unavailable_backend(caught.value) == "redis"


# --- The outage end to end -----------------------------------------------------


def _unreachable_session(*args: Any, **kwargs: Any) -> Any:
    raise _wrapped(DjangoOperationalError("x"), psycopg2.OperationalError("connection refused"))


@pytest.mark.django_db
def test_a_session_that_cannot_be_loaded_is_a_503(client, sample_user, mocker, outage_lines) -> None:
    """The session store is the first thing a signed-in request reads from Postgres."""
    from django.urls import reverse

    client.raise_request_exception = False
    client.force_login(sample_user)
    mocker.patch("django.contrib.sessions.backends.db.SessionStore.load", side_effect=_unreachable_session)

    response = client.get(reverse("core:dashboard"))

    assert response.status_code == 503
    assert response["Retry-After"] == str(RETRY_AFTER_SECONDS)
    assert outage_lines


@pytest.mark.django_db(transaction=True)
@pytest.mark.urls(__name__)
@pytest.mark.asyncio
async def test_an_outage_under_asgi_is_a_503_too(async_client, outage_lines) -> None:
    """Production serves through the ASGI handler, which converts exceptions in
    a worker thread. The cause still has to reach the outermost middleware."""
    async_client.raise_request_exception = False
    response = await async_client.get("/pg/")

    assert response.status_code == 503
    assert response["Retry-After"] == str(RETRY_AFTER_SECONDS)
    assert len(outage_lines) == 1


@pytest.mark.django_db
def test_a_tea_endpoint_answers_an_outage_with_a_json_503(client, mocker, outage_lines) -> None:
    from sbomify.apps.tea.mappers import TEA_API_VERSION

    client.raise_request_exception = False
    mocker.patch("sbomify.apps.tea.utils.get_workspace_from_request", side_effect=_unreachable_session)

    response = client.get(f"/tea/v{TEA_API_VERSION}/discovery?tei=urn:tei:uuid:example.com:x&workspace_key=k")

    assert response.status_code == 503
    assert response.json() == {"detail": "The service is temporarily unavailable. Please try again in a moment."}
    assert outage_lines


class _User:
    is_authenticated = True
    id = 7


async def _connect_to_workspace(user: Any) -> list[dict]:
    from sbomify.apps.core.consumers import WorkspaceConsumer

    sent: list[dict] = []
    inbox = [{"type": "websocket.connect"}]

    async def send(message: dict) -> None:
        sent.append(message)

    async def receive() -> dict:
        return inbox.pop(0) if inbox else {"type": "websocket.disconnect", "code": 1000}

    scope = {
        "type": "websocket",
        "path": "/ws/workspace/ws-key/",
        "url_route": {"kwargs": {"workspace_key": "ws-key"}},
        "user": user,
        "headers": [],
    }
    await WorkspaceConsumer.as_asgi()(scope, receive, send)
    return sent


@pytest.mark.asyncio
async def test_a_membership_check_on_an_unreachable_database_closes_with_1012(monkeypatch, outage_lines) -> None:
    from unittest.mock import AsyncMock

    from sbomify.apps.core.consumers import WS_CLOSE_SERVICE_RESTART, WorkspaceConsumer

    monkeypatch.setattr(WorkspaceConsumer, "_check_workspace_membership", AsyncMock(side_effect=_unreachable_session))

    sent = await _connect_to_workspace(_User())

    assert [m.get("code") for m in sent if m["type"] == "websocket.close"] == [WS_CLOSE_SERVICE_RESTART]
    assert len(outage_lines) == 1
    assert "websocket connect" in outage_lines[0].getMessage()


@pytest.mark.asyncio
async def test_a_membership_check_that_fails_otherwise_still_raises(monkeypatch, outage_lines) -> None:
    from unittest.mock import AsyncMock

    from sbomify.apps.core.consumers import WorkspaceConsumer

    monkeypatch.setattr(WorkspaceConsumer, "_check_workspace_membership", AsyncMock(side_effect=ValueError("a bug")))

    with pytest.raises(ValueError):
        await _connect_to_workspace(_User())
    assert outage_lines == []


def test_the_rate_limiter_reports_an_unreachable_redis_on_the_outage_line(mocker, outage_lines) -> None:
    from django.test import RequestFactory

    from sbomify.apps.access_tokens.throttling import AnonymousIPRateThrottle

    mocker.patch(
        "sbomify.apps.access_tokens.throttling.caches",
        new={"throttle": mocker.Mock(get=mocker.Mock(side_effect=RedisConnectionError("Error 111")))},
    )
    own_report = mocker.patch("sbomify.apps.access_tokens.throttling.logger")
    request = RequestFactory().get("/api/v1/anything", REMOTE_ADDR="203.0.113.7")
    throttle = AnonymousIPRateThrottle()

    assert [throttle.allow_request(request) for _ in range(3)] == [False, False, False]

    assert len(outage_lines) == 1
    assert "API rate limiter" in outage_lines[0].getMessage()
    own_report.exception.assert_not_called()


class TestAnOutageOverTime:
    """A blip reaches Sentry not at all; an outage that lasts reaches it once,
    as the sustained-fault line. Driven through the real console filter and
    ``before_send``, with the clock moved by hand."""

    @pytest.fixture
    def clock(self, mocker):
        now = [1_000_000.0]
        mocker.patch.object(sentry_config, "time", SimpleNamespace(monotonic=lambda: now[0]))
        return now

    @pytest.fixture
    def sustained(self):
        capture = _Capture()
        logger = logging.getLogger("sbomify.resilience")
        logger.addHandler(capture)
        try:
            yield capture.records
        finally:
            logger.removeHandler(capture)

    @staticmethod
    def _sent_to_sentry(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
        return [r for r in records if throttle_self_healing_notices({"e": 1}, {"log_record": r}) is not None]

    def _outage(self, clock: list[float], seconds: int) -> None:
        for _ in range(0, seconds, 10):
            report_backend_outage(
                _wrapped(DjangoOperationalError("x"), psycopg2.OperationalError("timeout expired")), "web request"
            )
            clock[0] += 10

    def test_a_blip_sends_nothing(self, clock, outage_lines, sustained) -> None:
        self._outage(clock, 60)

        assert len(outage_lines) == 6
        assert self._sent_to_sentry(outage_lines) == []
        assert sustained == []

    def test_an_outage_that_lasts_sends_the_sustained_line_once_a_window(self, clock, outage_lines, sustained) -> None:
        self._outage(clock, 330)

        assert self._sent_to_sentry(outage_lines) == []
        assert len(sustained) == 1
        assert self._sent_to_sentry(sustained) == sustained
