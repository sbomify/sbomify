"""Plugin paths that change what an artifact page shows tell the workspace.

- A Dependency-Track VEX sync that stores a new VEX row sends ``sbom_uploaded``,
  the same message and payload an upload sends.
- Queuing a re-run, or eagerly creating a delayed plugin's pending run, sends
  ``assessment_started`` so open pages show the run as pending.

Each is sent only once the change commits.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.plugins.tasks import enqueue_assessment
from sbomify.apps.plugins.tests.test_assessment_coverage import (  # noqa: F401
    NTIA,
    _client_as,
    _enable,
    billing_off,
    plugins,
)
from sbomify.apps.plugins.tests.test_dt_vex_sync import TRIAGED_VEX, _component_with_sbom, _version_row
from sbomify.apps.sboms.models import SBOM

pytestmark = pytest.mark.django_db


def _calls(mock_broadcast: Any, message_type: str) -> list[Any]:
    return [call for call in mock_broadcast.call_args_list if call.kwargs["message_type"] == message_type]


class TestDependencyTrackVexSync:
    def _sync(self, sbom: SBOM, existing: dict[str, Any] | None, capture: Any) -> MagicMock:
        client = MagicMock()
        client.get_project_vex.return_value = json.dumps(TRIAGED_VEX).encode()
        with (
            patch("sbomify.apps.core.object_store.StorageClient") as s3_cls,
            patch("sbomify.apps.sboms.services.sboms.schedule_vex_reapply"),
            patch("sbomify.apps.core.utils.broadcast_to_workspace") as mock_broadcast,
            capture(execute=True),
        ):
            s3 = s3_cls.return_value
            s3.upload_sbom.side_effect = lambda payload: "dt-vex.json"
            s3.get_sbom_data.side_effect = lambda name: json.dumps(existing).encode() if existing else None
            DependencyTrackPlugin()._sync_triage_vex(client, _version_row(sbom))
        return mock_broadcast

    def test_a_synced_vex_broadcasts_like_an_upload(
        self, sample_team_with_owner_member: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        component, sbom = _component_with_sbom(sample_team_with_owner_member.team)

        mock_broadcast = self._sync(sbom, None, django_capture_on_commit_callbacks)

        vex = SBOM.objects.get(component=component, bom_type=SBOM.BomType.VEX.value)
        calls = _calls(mock_broadcast, "sbom_uploaded")
        assert len(calls) == 1
        assert calls[0].kwargs["workspace_key"] == component.team.key
        assert calls[0].kwargs["data"] == {"sbom_id": str(vex.id), "component_id": str(component.id), "name": vex.name}

    def test_an_unchanged_export_broadcasts_nothing(
        self, sample_team_with_owner_member: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        component, sbom = _component_with_sbom(sample_team_with_owner_member.team)
        SBOM.objects.create(
            component=component,
            bom_type=SBOM.BomType.VEX.value,
            name="demo-app",
            version=sbom.version,
            format="cyclonedx",
            sbom_filename="existing-vex.json",
            source="dependency-track",
        )

        mock_broadcast = self._sync(sbom, TRIAGED_VEX, django_capture_on_commit_callbacks)

        assert _calls(mock_broadcast, "sbom_uploaded") == []


class TestAssessmentStarted:
    def test_a_rerun_broadcasts_assessment_started(
        self,
        sample_sbom: SBOM,
        sample_user: Any,
        plugins: Any,  # noqa: F811
        billing_off: Any,  # noqa: F811
        mocker: Any,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        _enable(sample_sbom.component.team, NTIA)
        mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")
        client: Client = _client_as(sample_sbom, sample_user, "owner")

        with (
            patch("sbomify.apps.plugins.tasks.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.post(f"/api/v1/plugins/assessments/{sample_sbom.id}/{NTIA}/rerun")

        assert response.status_code == 202, response.content
        mock_broadcast.assert_called_once()
        assert mock_broadcast.call_args.kwargs["workspace_key"] == sample_sbom.component.team.key
        assert mock_broadcast.call_args.kwargs["message_type"] == "assessment_started"
        assert mock_broadcast.call_args.kwargs["data"] == {
            "sbom_id": str(sample_sbom.id),
            "component_id": str(sample_sbom.component_id),
            "plugin_name": NTIA,
        }

    def test_a_refused_rerun_broadcasts_nothing(
        self,
        sample_sbom: SBOM,
        sample_user: Any,
        plugins: Any,  # noqa: F811
        billing_off: Any,  # noqa: F811
        mocker: Any,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        mocker.patch("sbomify.apps.plugins.apis.run_assessment_task.send")
        client: Client = _client_as(sample_sbom, sample_user, "owner")

        with (
            patch("sbomify.apps.plugins.tasks.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.post(f"/api/v1/plugins/assessments/{sample_sbom.id}/{NTIA}/rerun")

        assert response.status_code == 400
        mock_broadcast.assert_not_called()

    def test_a_delayed_plugins_pending_run_broadcasts_assessment_started(
        self,
        sample_sbom: SBOM,
        plugins: Any,  # noqa: F811
        billing_off: Any,  # noqa: F811
        mocker: Any,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        mocker.patch("sbomify.apps.plugins.tasks.run_assessment_task.send_with_options")

        with (
            patch("sbomify.apps.plugins.tasks.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            assert enqueue_assessment(
                sbom_id=sample_sbom.id, plugin_name=NTIA, run_reason=RunReason.ON_UPLOAD, delay_ms=1000
            )

        assert AssessmentRun.objects.filter(sbom=sample_sbom, plugin_name=NTIA, status="pending").exists()
        calls = _calls(mock_broadcast, "assessment_started")
        assert len(calls) == 1
        assert calls[0].kwargs["data"] == {
            "sbom_id": str(sample_sbom.id),
            "component_id": str(sample_sbom.component_id),
            "plugin_name": NTIA,
        }

    def test_an_immediate_enqueue_creates_no_pending_run_and_broadcasts_nothing(
        self,
        sample_sbom: SBOM,
        plugins: Any,  # noqa: F811
        billing_off: Any,  # noqa: F811
        mocker: Any,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        mocker.patch("sbomify.apps.plugins.tasks.run_assessment_task.send_with_options")

        with (
            patch("sbomify.apps.plugins.tasks.broadcast_to_workspace") as mock_broadcast,
            django_capture_on_commit_callbacks(execute=True),
        ):
            enqueue_assessment(sbom_id=sample_sbom.id, plugin_name=NTIA, run_reason=RunReason.ON_UPLOAD)

        assert _calls(mock_broadcast, "assessment_started") == []
