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
