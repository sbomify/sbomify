"""The cache, task broker and channel layer work against Valkey and against Redis.

sbomify ships with Valkey and supports Redis, and the two have diverged since
Valkey forked: different RDB formats, different release lines, scripting
engines maintained separately. Nothing in ``test_settings`` would notice a
break, because it swaps every one of these clients for an in-process stand-in.

These run each client the way ``settings.py`` builds it against the test stack's
server, whichever one that is, and skip without one. CI runs them once against
each image (``REDIS_IMAGE`` in ``docker-compose.tests.yml``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import dramatiq
import pytest
import redis
from channels_redis.core import RedisChannelLayer
from django.conf import settings
from django_redis.cache import RedisCache
from dramatiq import Worker
from dramatiq.results import Results
from dramatiq.results.backends.redis import RedisBackend
from redis.backoff import NoBackoff
from redis.retry import Retry

from sbomify import settings as production_settings
from sbomify.dramatiq_broker import RedisBroker


@pytest.fixture(scope="module")
def server() -> dict[str, Any]:
    """``INFO server`` of the test stack's server. Where none answers, the tests skip."""
    probe = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, retry=Retry(NoBackoff(), 0))
    try:
        info: dict[str, Any] = probe.info("server")
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
        pytest.skip("no server answers at REDIS_URL")
    finally:
        probe.close()
    return info


@pytest.fixture
def namespace() -> str:
    return f"test-{uuid4().hex}"


def _purge(url: str, namespace: str) -> None:
    client = redis.Redis.from_url(url)
    try:
        for key in client.scan_iter(f"*{namespace}*"):
            client.delete(key)
    finally:
        client.close()


def test_reports_which_server_it_ran_against(server: dict[str, Any], record_property: Any) -> None:
    # Valkey answers with both fields, ``redis_version`` pinned at 7.2.4 for
    # clients that gate features on it; Redis only with the one.
    name = "valkey" if "valkey_version" in server else "redis"
    version = server.get("valkey_version") or server["redis_version"]
    record_property("server", f"{name} {version}")
    assert int(str(version).split(".")[0]) >= 7


class TestCache:
    @pytest.fixture
    def caches(self, server: dict[str, Any], namespace: str) -> Iterator[dict[str, RedisCache]]:
        built = production_settings.build_redis_caches(settings.REDIS_CACHE_URL)
        caches = {
            alias: RedisCache(config["LOCATION"], {**config, "KEY_PREFIX": namespace})
            for alias, config in built.items()
        }
        try:
            yield caches
        finally:
            for cache in caches.values():
                cache.close()
            _purge(settings.REDIS_CACHE_URL, namespace)

    def test_every_operation_the_app_uses(self, caches: dict[str, RedisCache]) -> None:
        cache = caches["default"]

        cache.set("plain", {"nested": [1, 2]}, timeout=60)
        assert cache.get("plain") == {"nested": [1, 2]}

        assert cache.add("once", "first", timeout=60) is True
        assert cache.add("once", "second", timeout=60) is False
        assert cache.get("once") == "first"

        assert cache.touch("once", timeout=120) is True
        assert 60 < cache.ttl("once") <= 120

        cache.set("counter", 1, timeout=60)
        assert cache.incr("counter") == 2
        assert cache.incr("counter", 5) == 7

        cache.set_many({"tea:a": 1, "tea:b": 2, "other": 3}, timeout=60)
        assert cache.delete_pattern("tea:*") == 2
        assert cache.get_many(["tea:a", "tea:b", "other"]) == {"other": 3}

    def test_throttle_alias_shares_the_store(self, caches: dict[str, RedisCache]) -> None:
        caches["throttle"].set("window", 3, timeout=60)
        assert caches["default"].get("window") == 3


class TestTaskBroker:
    @pytest.fixture
    def broker(self, server: dict[str, Any], namespace: str) -> Iterator[RedisBroker]:
        options = production_settings.build_dramatiq_redis_options(settings.REDIS_WORKER_URL)
        broker = RedisBroker(namespace=namespace, **options)
        broker.add_middleware(Results(backend=RedisBackend(namespace=f"{namespace}-results", **options)))
        try:
            yield broker
        finally:
            broker.close()
            _purge(settings.REDIS_WORKER_URL, namespace)

    def test_runs_immediate_and_delayed_messages_and_stores_results(self, broker: RedisBroker) -> None:
        ran: list[str] = []

        def record(label: str) -> str:
            ran.append(label)
            return label.upper()

        actor = dramatiq.actor(record, broker=broker, queue_name="compat", store_results=True)
        now = actor.send("now")
        later = actor.send_with_options(args=("later",), delay=200)

        worker = Worker(broker, worker_timeout=100, worker_threads=2)
        worker.start()
        try:
            broker.join("compat", timeout=10_000)
            # A delayed message leaves the delay queue only once it has run.
            broker.join("compat.DQ", timeout=10_000)
            worker.join()
        finally:
            worker.stop(timeout=5_000)

        # Without ``backend`` dramatiq looks on the global broker, which under
        # test_settings is the stub.
        backend = broker.get_results_backend()
        assert sorted(ran) == ["later", "now"]
        assert now.get_result(backend=backend, block=True, timeout=5_000) == "NOW"
        assert later.get_result(backend=backend, block=True, timeout=5_000) == "LATER"


class TestChannelLayer:
    def test_group_send_reaches_every_member(self, server: dict[str, Any], namespace: str) -> None:
        config = production_settings.CHANNEL_LAYERS["default"]["CONFIG"]
        host = {**config["hosts"][0], "address": settings.REDIS_CHANNELS_URL}

        async def exchange() -> list[dict[str, Any]]:
            layer = RedisChannelLayer(hosts=[host], prefix=namespace, expiry=config["expiry"])
            try:
                first = await layer.new_channel()
                second = await layer.new_channel()
                await layer.group_add("workspace", first)
                await layer.group_add("workspace", second)
                await layer.group_send("workspace", {"type": "workspace.update", "id": "abc"})
                return [
                    await asyncio.wait_for(layer.receive(first), timeout=5),
                    await asyncio.wait_for(layer.receive(second), timeout=5),
                ]
            finally:
                await layer.flush()
                await layer.close_pools()

        received = asyncio.run(exchange())

        assert received == [{"type": "workspace.update", "id": "abc"}] * 2
