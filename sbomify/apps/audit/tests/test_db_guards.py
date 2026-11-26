"""The table is append-only because PostgreSQL says so, not because the ORM is polite."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from sbomify.apps.audit import db as audit_db
from sbomify.apps.audit.models import AuditEvent
from sbomify.apps.audit.services import purge_expired

from .conftest import postgres_only

pytestmark = [pytest.mark.django_db, postgres_only]


def _event(workspace_id: int, **fields) -> AuditEvent:
    return AuditEvent.objects.create(workspace_id=workspace_id, action="test.happened", actor_label="a@example.com", **fields)


def _sql(statement: str, params: list | None = None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, params or [])


def _refused(statement: str, params: list | None = None) -> None:
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            _sql(statement, params)


def _backdated(workspace_id: int, days: int) -> AuditEvent:
    """An event that happened ``days`` ago. Only reachable by switching a guard off."""
    event = _event(workspace_id)
    with transaction.atomic():
        _sql("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update")
        _sql(
            "UPDATE audit_events SET occurred_at = now() - make_interval(days => %s) WHERE id = %s",
            [days, event.pk],
        )
        _sql("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update")
    return event


def test_insert_is_sealed_by_the_database(enterprise):
    first = _event(enterprise.pk, occurred_at=timezone.now() - timedelta(days=900))
    second = _event(enterprise.pk)
    first.refresh_from_db()
    second.refresh_from_db()

    # The application's timestamp is ignored: an event cannot be backdated.
    assert timezone.now() - first.occurred_at < timedelta(minutes=1)
    assert (first.chain_seq, second.chain_seq) == (1, 2)
    assert first.prev_hash == ""
    assert second.prev_hash == first.entry_hash
    assert len(second.entry_hash) == 64


def test_chains_are_per_workspace(enterprise, sample_team):
    _event(enterprise.pk)
    other = _event(sample_team.pk)
    other.refresh_from_db()
    assert other.chain_seq == 1
    assert other.prev_hash == ""


def test_update_is_refused(enterprise):
    event = _event(enterprise.pk)
    _refused("UPDATE audit_events SET action = 'tampered' WHERE id = %s", [event.pk])
    event.refresh_from_db()
    assert event.action == "test.happened"


def test_delete_inside_retention_is_refused(enterprise):
    event = _event(enterprise.pk)
    _refused("DELETE FROM audit_events WHERE id = %s", [event.pk])
    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_truncate_is_refused(enterprise):
    _event(enterprise.pk)
    with transaction.atomic():
        # test_settings leaves this trigger out so Django can flush between
        # transactional tests; production always has it.
        _sql(audit_db.TRUNCATE_TRIGGER_SQL)
        _refused("TRUNCATE audit_events")
        _sql("DROP TRIGGER audit_events_no_truncate ON audit_events")
    assert AuditEvent.objects.filter(workspace_id=enterprise.pk).exists()


def test_the_production_install_blocks_truncate():
    assert audit_db.TRUNCATE_TRIGGER_SQL in audit_db.install_statements()


def test_orm_paths_are_refused(enterprise):
    event = _event(enterprise.pk)
    with pytest.raises(ValidationError):
        event.save()
    with pytest.raises(ValidationError):
        event.delete()
    with pytest.raises(ValidationError):
        AuditEvent.objects.filter(pk=event.pk).update(action="x")
    with pytest.raises(ValidationError):
        AuditEvent.objects.filter(pk=event.pk).delete()


def test_expired_events_can_be_deleted_and_purge_takes_only_those(enterprise):
    enterprise.audit_log_retention_days = 90
    enterprise.save()
    old = _backdated(enterprise.pk, days=91)
    recent = _backdated(enterprise.pk, days=89)
    fresh = _event(enterprise.pk)

    assert purge_expired() == 1
    remaining = set(AuditEvent.objects.filter(workspace_id=enterprise.pk).values_list("pk", flat=True))
    assert remaining == {recent.pk, fresh.pk}
    assert old.pk not in remaining


def test_retention_is_read_from_the_workspace_at_delete_time(enterprise):
    enterprise.audit_log_retention_days = 400
    enterprise.save()
    event = _backdated(enterprise.pk, days=380)
    _refused("DELETE FROM audit_events WHERE id = %s", [event.pk])


def test_retention_cannot_go_below_the_floor(enterprise):
    with pytest.raises(DatabaseError), transaction.atomic():
        _sql("UPDATE workspaces_workspaces SET audit_log_retention_days = 1 WHERE id = %s", [enterprise.pk])


def test_events_of_a_deleted_workspace_survive_it(enterprise):
    _event(enterprise.pk)
    workspace_id = enterprise.pk
    enterprise.delete()
    assert AuditEvent.objects.filter(workspace_id=workspace_id).exists()


def test_verify_chain_passes_then_catches_tampering(enterprise):
    for _ in range(3):
        _event(enterprise.pk)
    report = audit_db.verify_chain(enterprise.pk)
    assert report.ok
    assert report.checked == 3

    with transaction.atomic():
        _sql("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update")
        _sql("UPDATE audit_events SET target_label = 'edited' WHERE workspace_id = %s AND chain_seq = 2", [enterprise.pk])
        _sql("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update")

    assert audit_db.verify_chain(enterprise.pk).broken == (2,)


def test_verify_chain_catches_a_removed_entry(enterprise):
    for _ in range(3):
        _event(enterprise.pk)
    with transaction.atomic():
        _sql("ALTER TABLE audit_events DISABLE TRIGGER audit_events_guard_delete")
        _sql("DELETE FROM audit_events WHERE workspace_id = %s AND chain_seq = 2", [enterprise.pk])
        _sql("ALTER TABLE audit_events ENABLE TRIGGER audit_events_guard_delete")
    assert audit_db.verify_chain(enterprise.pk).broken == (3,)


def test_a_chain_trimmed_by_retention_still_verifies(enterprise):
    _backdated(enterprise.pk, days=400)
    for _ in range(2):
        _event(enterprise.pk)
    purge_expired()
    assert audit_db.verify_chain(enterprise.pk).ok


def _head(workspace_id: int) -> tuple[int, str, int]:
    with connection.cursor() as cursor:
        cursor.execute(audit_db.HEAD_SQL, [workspace_id])
        return cursor.fetchone()


def test_the_head_tracks_the_chain(enterprise):
    first = _event(enterprise.pk)
    second = _event(enterprise.pk)
    second.refresh_from_db()
    last_seq, last_hash, purged_through = _head(enterprise.pk)
    assert (last_seq, last_hash, purged_through) == (2, second.entry_hash, 0)
    assert first.pk


def test_the_head_only_moves_forward(enterprise):
    _event(enterprise.pk)
    _refused("UPDATE audit_chain_heads SET last_seq = 0 WHERE workspace_id = %s", [enterprise.pk])
    _refused("UPDATE audit_chain_heads SET last_hash = 'x' WHERE workspace_id = %s", [enterprise.pk])
    _refused("DELETE FROM audit_chain_heads WHERE workspace_id = %s", [enterprise.pk])


def test_sequence_numbers_never_restart_after_everything_expires(enterprise):
    enterprise.audit_log_retention_days = 30
    enterprise.save()
    _backdated(enterprise.pk, days=40)
    _backdated(enterprise.pk, days=40)
    assert purge_expired() == 2
    assert audit_db.verify_chain(enterprise.pk).ok

    fresh = _event(enterprise.pk)
    fresh.refresh_from_db()
    assert fresh.chain_seq == 3
    assert fresh.prev_hash != ""
    assert _head(enterprise.pk)[2] == 2
    assert audit_db.verify_chain(enterprise.pk).ok


def _delete_by_hand(workspace_id: int, where: str) -> None:
    with transaction.atomic():
        _sql("ALTER TABLE audit_events DISABLE TRIGGER audit_events_guard_delete")
        _sql(f"DELETE FROM audit_events WHERE workspace_id = %s AND {where}", [workspace_id])
        _sql("ALTER TABLE audit_events ENABLE TRIGGER audit_events_guard_delete")


def test_verify_chain_catches_removed_newest_entries(enterprise):
    for _ in range(3):
        _event(enterprise.pk)
    _delete_by_hand(enterprise.pk, "chain_seq = 3")
    report = audit_db.verify_chain(enterprise.pk)
    assert not report.ok
    assert report.broken == ()
    assert "newest" in report.problems[0]


def test_verify_chain_catches_an_old_end_cut_inside_retention(enterprise):
    for _ in range(3):
        _event(enterprise.pk)
    _delete_by_hand(enterprise.pk, "chain_seq = 1")
    report = audit_db.verify_chain(enterprise.pk)
    assert not report.ok
    assert "inside retention" in report.problems[0]


def test_verify_chain_catches_a_wiped_chain(enterprise):
    for _ in range(2):
        _event(enterprise.pk)
    _delete_by_hand(enterprise.pk, "true")
    assert not audit_db.verify_chain(enterprise.pk).ok


def test_a_test_database_can_be_flushed_even_after_the_migration_blocked_it():
    with transaction.atomic():
        audit_db.install(block_truncate=True)
        audit_db.install(block_truncate=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_trigger WHERE tgname LIKE '%%no_truncate'")
            assert cursor.fetchone()[0] == 0


def test_canonical_v1_is_frozen():
    """Every row sealed as v1 is verified against this exact SQL.

    If this fails, you edited the hash format. Restore v1 and add
    audit_events_canonical_v2 with a new hash_version instead.
    """
    import hashlib

    digest = hashlib.sha256(audit_db.CANONICAL_SQL.encode()).hexdigest()
    assert digest == "1f37399e28cb0202290a294ad1f23af264c1a9e1f031b9617a511a5dce0c2a1f"


def test_the_literal_sql_matches_the_constants():
    from sbomify.apps.audit.models import RETENTION_DEFAULT_DAYS, RETENTION_MIN_DAYS

    assert f"GREATEST(COALESCE(retention, {RETENTION_DEFAULT_DAYS}), {RETENTION_MIN_DAYS})" in audit_db.GUARD_DELETE_SQL
    assert f"NEW.hash_version := {audit_db.HASH_VERSION};" in audit_db.SEAL_SQL


def test_verify_chain_uses_one_snapshot_during_an_insert(enterprise):
    _event(enterprise.pk)
    inserted = False

    def insert_after_snapshot(execute, sql, params, many, context):
        nonlocal inserted
        result = execute(sql, params, many, context)
        if not inserted and sql.lstrip().startswith(("SELECT", "WITH")) and "audit_chain_heads" in sql:
            inserted = True
            # A second writer can commit after this SELECT's snapshot. Using
            # the same connection models that interleaving without threads.
            _event(enterprise.pk)
        return result

    with connection.execute_wrapper(insert_after_snapshot):
        report = audit_db.verify_chain(enterprise.pk)
    assert inserted
    assert AuditEvent.objects.filter(workspace_id=enterprise.pk).count() == 2
    assert report.ok, report
    assert report.checked == 1
