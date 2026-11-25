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
