"""A dropped Redis connection must not strand delayed task messages.

Dramatiq's consumer holds each delayed message in memory until it is due, and
throws that memory away when the connection drops. Redis still files those
messages as fetched by the worker, and hands a worker's messages back only once
its heartbeat has gone stale. A live worker heartbeats with every command, so
they waited for the next deploy, and an assessment run queued behind one of them
stayed pending, its artifact reading "Processing", for as long.

These run against the test stack's Redis. The outage is Redis refusing every
command while it lasts, which is what a worker sees while the server restarts,
once the client's own retries have given up.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import dramatiq
import pytest
import redis
from django.conf import settings
from django.utils.module_loading import import_string
from dramatiq import Worker
from dramatiq.errors import ConnectionClosed, QueueJoinTimeout
from dramatiq.middleware import Middleware

from sbomify import settings as production_settings
from sbomify.dramatiq_broker import RedisBroker

QUEUE = "delayed"


class _Outage(Middleware):
    """Redis refusing every command while ``refusing`` is set."""

    def __init__(self) -> None:
        self.refusing = threading.Event()
        self.begins_as_a_message_comes_due = False

    def before_enqueue(self, broker: dramatiq.Broker, message: dramatiq.Message[Any], delay: int | None) -> None:
        # Every test message is sent delayed, so only the worker enqueues one
        # without a delay: the moment it moves a due message onto its queue.
        if delay is None and self.begins_as_a_message_comes_due:
            self.begins_as_a_message_comes_due = False
            self.refusing.set()


@dataclass
class _Tasks:
    broker: RedisBroker
    outage: _Outage
    actor: dramatiq.Actor[[str], None]
    ran: list[str]

    def finish(self) -> None:
        """Wait until Redis has every message run and acknowledged."""
        try:
            self.broker.join(QUEUE, timeout=10_000)
        except QueueJoinTimeout:
            pytest.fail(f"messages were left unprocessed in Redis, and only {self.ran} ran")


@pytest.fixture
def tasks(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Tasks]:
    client = redis.Redis.from_url(settings.REDIS_WORKER_URL)
    outage = _Outage()
    send = client.execute_command

    def execute_command(*args: Any, **options: Any) -> Any:
        if outage.refusing.is_set():
            raise redis.ConnectionError("Connection refused.")
        return send(*args, **options)

    monkeypatch.setattr(client, "execute_command", execute_command)

    namespace = f"test-{uuid4().hex}"
    broker = RedisBroker(client=client, namespace=namespace, middleware=[outage])
    ran: list[str] = []

    def record(label: str) -> None:
        ran.append(label)

    actor = dramatiq.actor(record, broker=broker, queue_name=QUEUE)
    try:
        yield _Tasks(broker=broker, outage=outage, actor=actor, ran=ran)
    finally:
        outage.refusing.clear()
        for key in client.scan_iter(f"{namespace}:*"):
            client.delete(key)


@pytest.fixture
def worker(tasks: _Tasks, monkeypatch: pytest.MonkeyPatch) -> Iterator[Worker]:
    # Dramatiq waits three seconds before it reconnects, which teaches the tests nothing.
    monkeypatch.setattr("dramatiq.worker.CONSUMER_RESTART_DELAY_SECS", 0.05)
    worker = Worker(tasks.broker, worker_timeout=100, worker_threads=1)
    worker.start()
    try:
        yield worker
    finally:
        tasks.outage.refusing.clear()
        worker.stop(timeout=5_000)


def _held(worker: Worker) -> int:
    """Delayed messages the worker holds in memory, waiting for them to come due."""
    return worker.consumers[f"{QUEUE}.DQ"].delay_queue.qsize()


def _wait_until(condition: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + 10
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting until {what}")
        time.sleep(0.01)


def test_a_delayed_message_runs_after_the_connection_drops(tasks: _Tasks, worker: Worker) -> None:
    tasks.actor.send_with_options(args=("late",), delay=2_000)
    _wait_until(lambda: _held(worker) == 1, "the worker holds the message")

    tasks.outage.refusing.set()
    _wait_until(lambda: _held(worker) == 0, "the worker drops its copy")
    tasks.outage.refusing.clear()

    tasks.finish()
    assert tasks.ran == ["late"]


def test_delayed_messages_run_after_the_connection_drops_as_one_comes_due(tasks: _Tasks, worker: Worker) -> None:
    """The consumer's cleanup meets the outage too, which used to kill the consumer thread."""
    tasks.outage.begins_as_a_message_comes_due = True
    tasks.actor.send_with_options(args=("first",), delay=1_000)
    tasks.actor.send_with_options(args=("second",), delay=2_000)
    _wait_until(lambda: _held(worker) == 2, "the worker holds both messages")

    _wait_until(tasks.outage.refusing.is_set, "the first message comes due")
    _wait_until(lambda: _held(worker) == 0, "the worker drops its copies")
    tasks.outage.refusing.clear()

    tasks.finish()
    assert sorted(tasks.ran) == ["first", "second"]


def test_a_plain_queue_keeps_what_its_worker_is_running(tasks: _Tasks) -> None:
    """Only delay queues are handed back. A plain queue's fetched messages may be mid-run."""
    tasks.actor.send("now")
    assert next(tasks.broker.consume(QUEUE)) is not None

    # The queue's consumer restarts, as it does after a dropped connection.
    assert next(tasks.broker.consume(QUEUE)) is None


def test_an_outage_reaches_the_consumer_as_a_lost_connection(tasks: _Tasks) -> None:
    """The consumer reconnects quietly after a lost connection. Any other error it logs
    as unexpected, with a traceback, on every attempt for as long as the outage lasts.
    """
    tasks.outage.refusing.set()
    with pytest.raises(ConnectionClosed):
        tasks.broker.consume(f"{QUEUE}.DQ")


def test_the_worker_runs_this_broker() -> None:
    assert issubclass(import_string(production_settings.DRAMATIQ_BROKER["BROKER"]), RedisBroker)
