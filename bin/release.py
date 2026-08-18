#!/usr/bin/env python
"""Release script for production containers (distroless-compatible, no shell needed).

Runs database migrations and clears the Redis cache as part of the deployment process.

Pre-apply, the script logs the migration plan via ``migrate --plan`` so the
operator can grep the deploy log to see exactly which migrations a release is
about to apply. The plan is informational only — it does not gate the deploy;
if a destructive migration is unexpected, the operator must catch it in the
log review.

Concurrency
-----------
The whole migrate step is wrapped in a PostgreSQL *session-level advisory lock*.
Django does not serialise ``migrate`` itself, and two concurrent runners racing
the same migration deadlock or double-apply. That is not hypothetical under
Kubernetes: a Job is "at least once", so a node partition or an evicted pod can
leave two migration pods running at the same moment. The lock makes the second
one wait for the first instead of corrupting the schema.

The lock is advisory and session-scoped: it is released explicitly below, and by
the database automatically if the connection dies, so a killed pod cannot wedge
future deploys.
"""

import os
import sys
import time

import django
from django.db.backends.base.base import BaseDatabaseWrapper

# Arbitrary but STABLE application-wide identifier for the migration lock.
# Every runner must use the same value, so never change it casually.
MIGRATION_LOCK_ID = 8_675_309


def _log(message: str) -> None:
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


def _acquire_migration_lock(connection: BaseDatabaseWrapper, timeout: float) -> bool:
    """Take the advisory lock, polling so we can report progress while waiting.

    Returns True if the lock was acquired. Uses pg_try_advisory_lock rather than
    the blocking pg_advisory_lock so a stuck peer surfaces as a clear timeout
    instead of an indefinite hang with no output.
    """
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [MIGRATION_LOCK_ID])
            if cursor.fetchone()[0]:
                return True

        if time.monotonic() >= deadline:
            return False

        if not announced:
            _log(
                "[release] Another migration run holds the advisory lock; waiting "
                f"up to {timeout:.0f}s for it to finish..."
            )
            announced = True
        time.sleep(2)


def _release_migration_lock(connection: BaseDatabaseWrapper) -> None:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [MIGRATION_LOCK_ID])
    except Exception as e:  # noqa: BLE001 - releasing is best-effort; the session ending also frees it
        _log(f"[release] Warning: could not release the migration advisory lock: {e}")


def _apply_session_timeouts(connection: BaseDatabaseWrapper) -> None:
    """Bound how long a migration may block, when the operator asks for it.

    A migration that needs ACCESS EXCLUSIVE queues behind existing queries and,
    once queued, blocks every query that arrives after it — turning a fast
    ALTER TABLE into a site-wide stall. lock_timeout makes the migration give up
    and fail instead, so the deploy retries rather than taking traffic down.

    Both default to unset, which preserves the previous behaviour.
    """
    for env_var, statement in (
        ("MIGRATION_LOCK_TIMEOUT", "SET lock_timeout = %s"),
        ("MIGRATION_STATEMENT_TIMEOUT", "SET statement_timeout = %s"),
    ):
        value = os.environ.get(env_var, "").strip()
        if not value:
            continue
        with connection.cursor() as cursor:
            cursor.execute(statement, [value])
        _log(f"[release] {env_var}={value}")


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sbomify.settings")
    django.setup()

    from django.core.management import call_command
    from django.db import connection, connections

    lock_timeout = float(os.environ.get("MIGRATION_LOCK_WAIT_SECONDS", "600"))
    # Advisory locks are PostgreSQL-specific; skip the guard on other backends
    # (sqlite in tests) rather than crashing.
    use_lock = connection.vendor == "postgresql"

    lock_connection = None
    if use_lock:
        # Deliberately a dedicated connection, not the one `migrate` uses. The
        # lock is session scoped, so it lives and dies with its connection — if
        # anything in the migration path were to close or recycle the shared
        # connection, the lock would silently disappear underneath a migration
        # that is still running, which is precisely the window this is meant to
        # close.
        lock_connection = connections.create_connection("default")
        lock_connection.connect()

        if not _acquire_migration_lock(lock_connection, lock_timeout):
            _log(
                f"[release] ERROR: timed out after {lock_timeout:.0f}s waiting for the migration "
                "advisory lock. Another release is still running, or a previous one is wedged."
            )
            lock_connection.close()
            raise SystemExit(1)
        _log("[release] Acquired migration advisory lock.")
        # Timeouts go on the connection that actually runs the DDL.
        _apply_session_timeouts(connection)

    try:
        # Log the migration plan BEFORE applying. `--plan` only prints which
        # migrations would run, in order — it doesn't apply anything, so it's
        # safe to run unconditionally. Output goes to stdout, captured by
        # container logs / deploy log aggregation. Operators can grep for
        # "[release] Migration plan:" to find this section in the deploy log.
        _log("[release] Migration plan:")
        call_command("migrate", "--plan", "--no-input")

        _log("[release] Applying migrations...")
        call_command("migrate", "--no-input")
        _log("[release] Migrations applied successfully.")
    finally:
        if lock_connection is not None:
            _release_migration_lock(lock_connection)
            lock_connection.close()

    from django.core.cache import cache

    try:
        cache.clear()
        _log("[release] Redis cache cleared.")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Warning: Could not clear Redis cache: {e}\n")


if __name__ == "__main__":
    main()
