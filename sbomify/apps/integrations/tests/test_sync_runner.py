"""The provider-agnostic sync runner and the scheduled task."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.core.domain.exceptions import ExternalServiceError
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.integrations.exceptions import ProviderAuthError
from sbomify.apps.integrations.models import Integration
from sbomify.apps.integrations.services import sync as sync_module
from sbomify.apps.integrations.services.sync import run_sync
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

pytestmark = pytest.mark.django_db


def _install(monkeypatch, fn) -> None:
    monkeypatch.setattr(sync_module, "import_string", lambda path: fn)


class TestRunSync:
    def test_a_good_run_records_when_and_what(self, connected_vanta, monkeypatch) -> None:
        _install(monkeypatch, lambda integration: ServiceResult.success({"frameworks": 2, "controls": 40}))

        result = run_sync(connected_vanta)

        assert result.ok
        connected_vanta.refresh_from_db()
        assert connected_vanta.last_sync_status == Integration.SyncStatus.OK
        assert connected_vanta.last_sync_at is not None
        assert connected_vanta.last_sync_summary == {"frameworks": 2, "controls": 40}
        assert connected_vanta.last_sync_error == ""

    def test_a_previous_error_is_cleared_by_a_good_run(self, connected_vanta, monkeypatch) -> None:
        connected_vanta.last_sync_status = Integration.SyncStatus.FAILED
        connected_vanta.last_sync_error = "Vanta returned 500"
        connected_vanta.save()
        _install(monkeypatch, lambda integration: ServiceResult.success({}))

        run_sync(connected_vanta)

        connected_vanta.refresh_from_db()
        assert connected_vanta.last_sync_error == ""

    def test_a_dead_credential_is_recorded_rather_than_raised(self, connected_vanta, monkeypatch) -> None:
        def refuse(integration):
            raise ProviderAuthError("Vanta needs reconnecting.", service="vanta")

        _install(monkeypatch, refuse)

        result = run_sync(connected_vanta)

        assert not result.ok
        connected_vanta.refresh_from_db()
        assert connected_vanta.last_sync_status == Integration.SyncStatus.FAILED
        assert "reconnecting" in connected_vanta.last_sync_error

    def test_an_unreachable_provider_is_recorded(self, connected_vanta, monkeypatch) -> None:
        def unavailable(integration):
            raise ExternalServiceError("Vanta returned 503", service="vanta")

        _install(monkeypatch, unavailable)

        assert not run_sync(connected_vanta).ok
        connected_vanta.refresh_from_db()
        assert connected_vanta.last_sync_status == Integration.SyncStatus.FAILED

    def test_an_unexpected_crash_does_not_escape(self, connected_vanta, monkeypatch) -> None:
        """A broken sync must not poison the task queue."""

        def boom(integration):
            raise ZeroDivisionError("oops")

        _install(monkeypatch, boom)

        result = run_sync(connected_vanta)

        assert not result.ok
        connected_vanta.refresh_from_db()
        assert connected_vanta.last_sync_status == Integration.SyncStatus.FAILED

    def test_a_failed_result_is_recorded_too(self, connected_vanta, monkeypatch) -> None:
        _install(monkeypatch, lambda integration: ServiceResult.failure("no frameworks", status_code=400))

        assert not run_sync(connected_vanta).ok
        connected_vanta.refresh_from_db()
        assert connected_vanta.last_sync_error == "no frameworks"

    def test_a_provider_that_is_no_longer_registered_fails_cleanly(self, connected_vanta) -> None:
        connected_vanta.provider = "gone"
        connected_vanta.save()

        result = run_sync(connected_vanta)

        assert not result.ok
        assert result.status_code == 400


class TestScheduling:
    def test_queues_only_the_stale_connections(self, connected_vanta, monkeypatch) -> None:
        from sbomify.apps.integrations import tasks

        queued: list[str] = []
        monkeypatch.setattr(tasks.sync_integration, "send", lambda integration_id: queued.append(integration_id))

        connected_vanta.last_sync_at = timezone.now()
        connected_vanta.save()
        tasks.sync_due_integrations()
        assert queued == []

        connected_vanta.last_sync_at = timezone.now() - tasks.SYNC_INTERVAL - timedelta(minutes=1)
        connected_vanta.save()
        tasks.sync_due_integrations()
        assert queued == [connected_vanta.id]

    def test_a_never_synced_connection_is_due(self, connected_vanta, monkeypatch) -> None:
        from sbomify.apps.integrations import tasks

        queued: list[str] = []
        monkeypatch.setattr(tasks.sync_integration, "send", lambda integration_id: queued.append(integration_id))

        tasks.sync_due_integrations()

        assert queued == [connected_vanta.id]

    def test_a_connection_needing_a_reconnect_is_skipped(self, connected_vanta, monkeypatch) -> None:
        """There is no credential to try, so queueing it only refills the error log."""
        from sbomify.apps.integrations import tasks

        queued: list[str] = []
        monkeypatch.setattr(tasks.sync_integration, "send", lambda integration_id: queued.append(integration_id))

        connected_vanta.status = Integration.Status.REVOKED
        connected_vanta.save()
        tasks.sync_due_integrations()

        assert queued == []

    def test_syncing_a_deleted_connection_is_a_no_op(self, monkeypatch) -> None:
        from sbomify.apps.integrations import tasks

        monkeypatch.setattr(tasks, "run_sync", lambda integration: pytest.fail("should not have run"))

        tasks.sync_integration("nonexistent1")


def _records_into(runs: list[str]):
    """A ``run_sync`` that only says which connection reached it."""

    def _run(integration) -> ServiceResult[dict]:
        runs.append(integration.id)
        return ServiceResult.success({})

    return _run


class TestClaimingAConnection:
    """One run per connection at a time, and none at all once it is gone."""

    def test_a_run_already_under_way_is_not_joined(self, connected_vanta, monkeypatch) -> None:
        """Sync now, the OAuth callback and the scheduler can all queue the same row.

        Two runs against one account duplicate every per-control request and
        let the slower one write its older answers last.
        """
        from sbomify.apps.integrations import tasks

        runs: list[str] = []
        monkeypatch.setattr(tasks, "run_sync", _records_into(runs))

        connected_vanta.last_sync_status = Integration.SyncStatus.RUNNING
        connected_vanta.save()

        tasks.sync_integration(connected_vanta.id)

        assert runs == []

    def test_a_claim_from_a_worker_that_died_expires(self, connected_vanta, monkeypatch) -> None:
        """Otherwise a killed worker ends syncing for that workspace for good."""
        from sbomify.apps.integrations import tasks

        runs: list[str] = []
        monkeypatch.setattr(tasks, "run_sync", _records_into(runs))

        Integration.objects.filter(pk=connected_vanta.pk).update(
            last_sync_status=Integration.SyncStatus.RUNNING,
            updated_at=timezone.now() - tasks.SYNC_LEASE - timedelta(minutes=1),
        )

        tasks.sync_integration(connected_vanta.id)

        assert runs == [connected_vanta.id]

    def test_a_disconnect_cancels_work_already_queued(self, connected_vanta, monkeypatch) -> None:
        """The check has to be here, not at queueing time.

        A queued task that loaded the row before the disconnect still holds the
        credential, and would go on updating catalogs for an account nobody is
        connected to.
        """
        from sbomify.apps.integrations import tasks

        monkeypatch.setattr(tasks, "run_sync", lambda integration: pytest.fail("should not have run"))

        integration_id = connected_vanta.id
        connected_vanta.delete()

        tasks.sync_integration(integration_id)

    def test_a_connection_needing_a_reconnect_is_not_claimed(self, connected_vanta, monkeypatch) -> None:
        from sbomify.apps.integrations import tasks

        monkeypatch.setattr(tasks, "run_sync", lambda integration: pytest.fail("should not have run"))

        connected_vanta.status = Integration.Status.REVOKED
        connected_vanta.save()

        tasks.sync_integration(connected_vanta.id)

    def test_claiming_marks_the_connection_as_syncing(self, connected_vanta, monkeypatch) -> None:
        from sbomify.apps.integrations import tasks

        seen: list[str] = []

        def record(integration):
            seen.append(Integration.objects.get(pk=integration.pk).last_sync_status)
            return ServiceResult.success({})

        monkeypatch.setattr(tasks, "run_sync", record)

        tasks.sync_integration(connected_vanta.id)

        assert seen == [Integration.SyncStatus.RUNNING]


class TestASupersededRunDoesNotReportItsResult:
    """A reconnect moves ``connected_at``, and the run that missed it loses."""

    def test_a_result_from_the_replaced_credential_is_dropped(self, connected_vanta, monkeypatch) -> None:
        def reconnect_then_succeed(integration):
            Integration.objects.filter(pk=integration.pk).update(
                connected_at=timezone.now(), last_sync_status=Integration.SyncStatus.OK
            )
            return ServiceResult.success({"frameworks": 1})

        _install(monkeypatch, reconnect_then_succeed)

        run_sync(connected_vanta)

        stored = Integration.objects.get(pk=connected_vanta.pk)
        assert stored.last_sync_summary == {}
        assert stored.last_sync_at is None

    def test_a_failure_from_the_replaced_credential_is_dropped_too(self, connected_vanta, monkeypatch) -> None:
        """A superseded run must not put the new connection into a failed state."""

        def reconnect_then_fail(integration):
            Integration.objects.filter(pk=integration.pk).update(
                connected_at=timezone.now(), last_sync_status=Integration.SyncStatus.OK
            )
            raise ExternalServiceError("Vanta is not answering.")

        _install(monkeypatch, reconnect_then_fail)

        run_sync(connected_vanta)

        assert Integration.objects.get(pk=connected_vanta.pk).last_sync_status == Integration.SyncStatus.OK

    def test_a_superseded_run_does_not_re_claim_the_connection(self, connected_vanta, monkeypatch) -> None:
        """The opening RUNNING write is a write like any other.

        Unconditional, it was a way to undo a reconnect: `save_connection`
        clears the claim so the queued replacement can take it, and a stale
        worker writing RUNNING through its old instance blocks that replacement
        for the lease.
        """
        Integration.objects.filter(pk=connected_vanta.pk).update(
            connected_at=timezone.now(), last_sync_status=Integration.SyncStatus.NEVER
        )
        _install(monkeypatch, lambda integration: ServiceResult.success({}))

        run_sync(connected_vanta)

        assert Integration.objects.get(pk=connected_vanta.pk).last_sync_status == Integration.SyncStatus.NEVER

    def test_an_ordinary_run_still_records_its_result(self, connected_vanta, monkeypatch) -> None:
        _install(monkeypatch, lambda integration: ServiceResult.success({"frameworks": 2}))

        run_sync(connected_vanta)

        stored = Integration.objects.get(pk=connected_vanta.pk)
        assert stored.last_sync_status == Integration.SyncStatus.OK
        assert stored.last_sync_summary == {"frameworks": 2}
        assert stored.last_sync_at is not None
