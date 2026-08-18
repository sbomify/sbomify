"""Tests for the advisory lock in bin/release.py.

The lock is what stops two concurrent deploys from applying migrations at the
same time. Kubernetes Jobs are "at least once", so a node partition really can
leave two migration pods running, and Django does not serialise `migrate`
itself. These tests pin the behaviour the chart depends on.
"""

import importlib.util
from pathlib import Path

import pytest
from django.db import connection, connections

RELEASE_SCRIPT = Path(__file__).resolve().parents[4] / "bin" / "release.py"


def _load_release_module():
    """Import bin/release.py, which lives outside the package tree."""
    spec = importlib.util.spec_from_file_location("release_script", RELEASE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release():
    return _load_release_module()


@pytest.fixture
def other_connection():
    """A second database connection, standing in for a competing deploy."""
    conn = connections.create_connection("default")
    conn.connect()
    try:
        yield conn
    finally:
        conn.close()


def _try_lock(conn, lock_id) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_id])
        return cursor.fetchone()[0]


def _unlock(conn, lock_id) -> None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])


@pytest.mark.django_db(transaction=True)
def test_release_script_exists_and_defines_a_stable_lock_id(release):
    # The id must be stable across versions: two runners only serialise if they
    # agree on it, so a casual change silently disables the protection.
    assert release.MIGRATION_LOCK_ID == 8_675_309


@pytest.mark.django_db(transaction=True)
def test_acquire_and_release_round_trip(release):
    assert release._acquire_migration_lock(connection, timeout=5) is True
    release._release_migration_lock(connection)

    # Once released, the lock is free again.
    assert release._acquire_migration_lock(connection, timeout=5) is True
    release._release_migration_lock(connection)


@pytest.mark.django_db(transaction=True)
def test_second_runner_is_blocked_while_the_lock_is_held(release, other_connection):
    """The whole point: a competing deploy must not migrate concurrently."""
    assert release._acquire_migration_lock(connection, timeout=5) is True
    try:
        # A different session cannot take the same lock...
        assert _try_lock(other_connection, release.MIGRATION_LOCK_ID) is False

        # ...and a second runner gives up rather than proceeding in parallel.
        assert release._acquire_migration_lock(other_connection, timeout=1) is False
    finally:
        release._release_migration_lock(connection)

    # With the holder gone, the waiting runner gets through.
    assert _try_lock(other_connection, release.MIGRATION_LOCK_ID) is True
    _unlock(other_connection, release.MIGRATION_LOCK_ID)


@pytest.mark.django_db(transaction=True)
def test_lock_is_released_when_the_session_dies(release, other_connection):
    """A killed migration pod must not wedge every future deploy.

    Session-level advisory locks are dropped by PostgreSQL when the connection
    goes away, which is what makes the lock safe to use from a pod that can be
    evicted at any moment.
    """
    assert _try_lock(other_connection, release.MIGRATION_LOCK_ID) is True

    # Simulate the pod disappearing without a clean release.
    other_connection.close()

    assert release._acquire_migration_lock(connection, timeout=10) is True
    release._release_migration_lock(connection)


@pytest.mark.django_db(transaction=True)
def test_session_timeouts_are_applied_only_when_configured(release, monkeypatch):
    def current(setting: str) -> str:
        with connection.cursor() as cursor:
            cursor.execute(f"SHOW {setting}")
            return cursor.fetchone()[0]

    monkeypatch.delenv("MIGRATION_LOCK_TIMEOUT", raising=False)
    monkeypatch.delenv("MIGRATION_STATEMENT_TIMEOUT", raising=False)
    before = current("lock_timeout")
    release._apply_session_timeouts(connection)
    assert current("lock_timeout") == before, "unset env must not change the session"

    monkeypatch.setenv("MIGRATION_LOCK_TIMEOUT", "1500ms")
    release._apply_session_timeouts(connection)
    assert current("lock_timeout") == "1500ms"

    # Reset so we do not leak the setting into other tests on this connection.
    with connection.cursor() as cursor:
        cursor.execute("SET lock_timeout = DEFAULT")
