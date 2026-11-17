"""A finished sync tells the workspace, so an open integrations tab repaints.

The panel listens for ``integration_synced``. Every member hears it, so it
carries the outcome and never the provider's error text.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.integrations import tasks
from sbomify.apps.integrations.models import Integration
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

BROADCAST = "sbomify.apps.teams.broadcasts.broadcast_to_workspace"

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        (ServiceResult.success({"frameworks": 1}), "ok"),
        (ServiceResult.failure("Vanta returned 500 with secret detail", status_code=502), "failed"),
    ],
)
def test_a_finished_sync_broadcasts_its_outcome(
    outcome: ServiceResult[dict[str, Any]],
    status: str,
    connected_vanta: Integration,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    monkeypatch.setattr(tasks, "run_sync", lambda integration: outcome)

    with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
        tasks.sync_integration(connected_vanta.id)

    mock_broadcast.assert_called_once_with(
        workspace_key=connected_vanta.team.key,
        message_type="integration_synced",
        data={"integration_id": str(connected_vanta.id), "provider": "vanta", "status": status},
    )


def test_a_skipped_sync_broadcasts_nothing(
    connected_vanta: Integration,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    monkeypatch.setattr(tasks, "run_sync", lambda integration: pytest.fail("should not have run"))
    connected_vanta.last_sync_status = Integration.SyncStatus.RUNNING
    connected_vanta.save()

    with patch(BROADCAST) as mock_broadcast, django_capture_on_commit_callbacks(execute=True):
        tasks.sync_integration(connected_vanta.id)

    mock_broadcast.assert_not_called()


def test_the_settings_tab_repaints_on_a_sync(admin_client_for_team: Any, sample_team_with_owner_member: Any) -> None:  # noqa: F811
    from django.urls import reverse

    team = sample_team_with_owner_member.team
    response = admin_client_for_team.get(
        reverse("workspaces:team_settings_tab", kwargs={"workspace_key": team.key, "tab": "integrations"})
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert "liveRegion({ refresh: ['integration_synced']" in html
    assert "live-refresh" in html
    assert "refreshIntegrations" in html
