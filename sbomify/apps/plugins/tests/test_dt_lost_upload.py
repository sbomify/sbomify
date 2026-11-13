"""A scan whose upload Dependency Track lost has the tree send the BOM again.

A scan only polls the tree project holding its SBOM, and every poll that comes
back empty asks for another retry. An upload DT lost, failed or never analysed
would keep asking forever, settling on "Could not scan". So such a poll forgets
the project: the tree's next sync finds or makes it again and uploads the BOM,
and the scan waits on that upload. DT being down, or merely slow, is not that.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
from sbomify.apps.plugins.sdk.base import RetryLaterError
from sbomify.apps.vulnerability_scanning.clients import DependencyTrackAPIError

TREE = "sbomify.apps.vulnerability_scanning.services.dt_release_tree"
ANALYSED = {"lastBomImport": 1762196390000, "lastVulnerabilityAnalysis": 1762196400000}
NOT_ANALYSED = {"lastBomImport": 1762196390000, "lastVulnerabilityAnalysis": None}


@pytest.mark.django_db
class TestALostUploadIsSentAgain:
    @pytest.fixture
    def scan(self, tmp_path):
        from sbomify.apps.core.models import Component
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.teams.models import Workspace
        from sbomify.apps.vulnerability_scanning.models import DependencyTrackServer, DependencyTrackTreeProject

        team = Workspace.objects.create(name="DT Lost Team", key="dtlostteam", billing_plan="business")
        server = DependencyTrackServer.objects.create(
            name="DT Lost Server", url="https://dt-lost.example.com", api_key="key", health_status="healthy"
        )
        component = Component.objects.create(name="DT Lost Component", team=team)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", format_version="1.6")
        path = tmp_path / "sbom.cdx.json"
        path.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1}))
        holder = DependencyTrackTreeProject.objects.create(
            dt_server=server,
            team=team,
            kind=DependencyTrackTreeProject.Kind.LATEST_COMPONENT,
            component=component,
            sbom=sbom,
            dt_project_uuid=uuid.uuid4(),
            dt_name="dev dtlostteam · DT Lost Component",
            dt_version="latest",
            last_bom_upload=timezone.now() - timedelta(days=3),
        )
        return SimpleNamespace(team=team, sbom=sbom, path=path, server=server, holder=holder)

    @staticmethod
    def _client(*, metrics: dict | Exception, project: dict | Exception) -> MagicMock:
        client = MagicMock()
        if isinstance(metrics, Exception):
            client.get_project_metrics.side_effect = metrics
        else:
            client.get_project_metrics.return_value = metrics
        if isinstance(project, Exception):
            client.get_project.side_effect = project
        else:
            client.get_project.return_value = project
        client.get_project_vulnerabilities.return_value = {"content": []}
        return client

    @staticmethod
    def _assess(scan, client: MagicMock) -> tuple[MagicMock, object]:
        """Run a scan; returns the tree's sync queue and the outcome."""
        with (
            patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=True),
            patch(f"{TREE}.workspace_server", return_value=scan.server),
            patch(f"{TREE}.queue_sync") as queued,
            patch("sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient", return_value=client),
        ):
            try:
                outcome: object = DependencyTrackPlugin().assess(str(scan.sbom.id), scan.path)
            except RetryLaterError as retry:
                outcome = retry
        return queued, outcome

    @staticmethod
    def _project_kept(scan) -> bool:
        return type(scan.holder).objects.filter(pk=scan.holder.pk).exists()

    def _uploaded_at(self, scan, when) -> None:
        type(scan.holder).objects.filter(pk=scan.holder.pk).update(last_bom_upload=when)

    def test_a_project_dt_no_longer_has_is_sent_again(self, scan) -> None:
        gone = DependencyTrackAPIError("Dependency Track error (404): The project could not be found.", 404)

        queued, outcome = self._assess(scan, self._client(metrics=gone, project=NOT_ANALYSED))

        queued.assert_called_once_with(scan.team.id)
        assert isinstance(outcome, RetryLaterError)
        assert "uploaded again" in str(outcome)
        assert not self._project_kept(scan)

    def test_an_upload_dt_never_analysed_is_sent_again_after_a_day(self, scan) -> None:
        queued, outcome = self._assess(scan, self._client(metrics={}, project=NOT_ANALYSED))

        queued.assert_called_once()
        assert isinstance(outcome, RetryLaterError)
        assert not self._project_kept(scan)

    def test_an_upload_from_today_keeps_waiting(self, scan) -> None:
        """DT can sit on a backlog for hours. Sending the same BOM again would only add to it."""
        self._uploaded_at(scan, timezone.now() - timedelta(hours=6))

        queued, outcome = self._assess(scan, self._client(metrics={}, project=NOT_ANALYSED))

        queued.assert_not_called()
        assert isinstance(outcome, RetryLaterError)
        assert "still processing" in str(outcome)
        assert self._project_kept(scan)

    def test_dt_being_down_is_not_read_as_a_lost_upload(self, scan) -> None:
        down = DependencyTrackAPIError("Dependency Track error (503): Service Unavailable", 503)

        queued, outcome = self._assess(scan, self._client(metrics=down, project=NOT_ANALYSED))

        queued.assert_not_called()
        assert isinstance(outcome, RetryLaterError)
        assert self._project_kept(scan)

    def test_a_failed_project_read_is_not_read_as_a_lost_upload(self, scan) -> None:
        """The metrics answer empty, then the project read fails: DT has not said
        whether it analysed the upload, so the project stays on record."""
        down = DependencyTrackAPIError("Dependency Track error (503): Service Unavailable", 503)

        queued, outcome = self._assess(scan, self._client(metrics={}, project=down))

        queued.assert_not_called()
        assert isinstance(outcome, RetryLaterError)
        assert self._project_kept(scan)

    def test_an_analysed_project_is_read_not_sent_again(self, scan) -> None:
        """The hourly rescan of a healthy SBOM, whose upload is weeks old."""
        queued, outcome = self._assess(scan, self._client(metrics={}, project=ANALYSED))

        queued.assert_not_called()
        assert outcome.summary.total_findings == 0
        assert self._project_kept(scan)

    def _with_token(self, scan, processing: dict) -> MagicMock:
        type(scan.holder).objects.filter(pk=scan.holder.pk).update(dt_upload_token=uuid.uuid4())
        client = self._client(metrics={"vulnerabilities": 0}, project=ANALYSED)
        client.get_upload_processing.return_value = processing
        return client

    def test_an_upload_dt_says_it_is_processing_after_a_day_is_sent_again(self, scan) -> None:
        queued, outcome = self._assess(scan, self._with_token(scan, {"processing": True, "status": "PENDING"}))

        queued.assert_called_once()
        assert isinstance(outcome, RetryLaterError)
        assert not self._project_kept(scan)

    def test_an_upload_dt_is_processing_since_today_keeps_waiting(self, scan) -> None:
        self._uploaded_at(scan, timezone.now() - timedelta(hours=6))

        queued, outcome = self._assess(scan, self._with_token(scan, {"processing": True, "status": "RUNNING"}))

        queued.assert_not_called()
        assert isinstance(outcome, RetryLaterError)
        assert "still processing" in str(outcome)
        assert self._project_kept(scan)

    def test_an_upload_dt_failed_to_process_is_reported_and_sent_again(self, scan) -> None:
        """DT 5 reports FAILED and stops. Reading the project then would return the
        previous upload's findings, or none."""
        self._uploaded_at(scan, timezone.now() - timedelta(minutes=5))
        client = self._with_token(scan, {"processing": False, "status": "FAILED"})

        queued, outcome = self._assess(scan, client)

        client.get_project_vulnerabilities.assert_not_called()
        assert outcome.summary.error_count == 1
        assert "could not process this SBOM" in outcome.findings[0].description
        queued.assert_called_once()
        assert not self._project_kept(scan)
