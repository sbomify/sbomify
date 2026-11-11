"""A Dependency Track upload that DT lost is sent again, not polled forever.

A scan with a project version on record only polls it, and every poll that comes
back without an analysis asks to be retried. When DT lost the upload, through an
outage or a restart that dropped its queue, no number of polls brings it back: the
scan runs out of retries and settles on "Could not scan", and every scheduled
rescan after it does the same. These drive the real ``assess()``, which is what the
hourly rescan calls.
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
from sbomify.apps.plugins.sdk.base import RetryLaterError, SBOMContext
from sbomify.apps.vulnerability_scanning.clients import DependencyTrackAPIError

ANALYSED = {"lastBomImport": 1762196390000, "lastVulnerabilityAnalysis": 1762196400000}
NOT_ANALYSED = {"lastBomImport": 1762196390000, "lastVulnerabilityAnalysis": None}


@pytest.mark.django_db
class TestALostUploadIsSentAgain:
    @pytest.fixture
    def scan(self, tmp_path):
        from sbomify.apps.core.models import Component, Product
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.teams.models import Workspace
        from sbomify.apps.vulnerability_scanning.models import (
            DependencyTrackServer,
            SbomDependencyTrackProjectVersion,
        )

        team = Workspace.objects.create(name="DT Lost Team", key="dtlostteam", billing_plan="business")
        server = DependencyTrackServer.objects.create(
            name="DT Lost Server", url="https://dt-lost.example.com", api_key="key", health_status="healthy"
        )
        component = Component.objects.create(name="DT Lost Component", team=team)
        product = Product.objects.create(name="DT Lost Product", team=team)
        product.components.add(component)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", format_version="1.6")
        path = tmp_path / "sbom.cdx.json"
        path.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1}))
        row = SbomDependencyTrackProjectVersion.objects.create(
            sbom=sbom,
            dt_server=server,
            dt_project_version=str(sbom.id),
            dt_project_version_uuid=uuid.uuid4(),
            last_sbom_upload=timezone.now() - timedelta(days=3),
        )
        return SimpleNamespace(sbom=sbom, path=path, server=server, row=row)

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
    def _assess(scan, client: MagicMock, context: SBOMContext | None = None) -> tuple[MagicMock, object]:
        upload = MagicMock(return_value=SimpleNamespace(dt_project_version_uuid=uuid.uuid4(), dt_project_version="v"))
        with (
            patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=True),
            patch.object(DependencyTrackPlugin, "_select_dt_server", return_value=scan.server),
            patch.object(DependencyTrackPlugin, "_resolve_release_context", return_value=[]),
            patch.object(DependencyTrackPlugin, "_upload_new_sbom_version", upload),
            patch("sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient", return_value=client),
        ):
            try:
                outcome: object = DependencyTrackPlugin().assess(str(scan.sbom.id), scan.path, context=context)
            except RetryLaterError as retry:
                outcome = retry
        return upload, outcome

    @staticmethod
    def _row_kept(scan) -> bool:
        from sbomify.apps.vulnerability_scanning.models import SbomDependencyTrackProjectVersion

        return SbomDependencyTrackProjectVersion.objects.filter(pk=scan.row.pk).exists()

    def test_a_version_dt_no_longer_has_is_uploaded_again(self, scan) -> None:
        gone = DependencyTrackAPIError("Dependency Track error (404): The project could not be found.", 404)

        upload, outcome = self._assess(scan, self._client(metrics=gone, project=NOT_ANALYSED))

        upload.assert_called_once()
        assert isinstance(outcome, RetryLaterError)
        assert "uploaded" in str(outcome)
        assert not self._row_kept(scan)

    def test_an_upload_dt_never_analysed_is_uploaded_again_after_a_day(self, scan) -> None:
        upload, outcome = self._assess(scan, self._client(metrics={}, project=NOT_ANALYSED))

        upload.assert_called_once()
        assert isinstance(outcome, RetryLaterError)
        assert not self._row_kept(scan)

    def test_an_upload_from_today_keeps_waiting(self, scan) -> None:
        """DT can sit on a backlog for hours. Sending the same BOM again would
        only add to it."""
        scan.row.last_sbom_upload = timezone.now() - timedelta(hours=6)
        scan.row.save(update_fields=["last_sbom_upload"])

        upload, outcome = self._assess(scan, self._client(metrics={}, project=NOT_ANALYSED))

        upload.assert_not_called()
        assert isinstance(outcome, RetryLaterError)
        assert "still processing" in str(outcome)
        assert self._row_kept(scan)

    def test_dt_being_down_is_not_read_as_a_lost_upload(self, scan) -> None:
        down = DependencyTrackAPIError("Dependency Track error (503): Service Unavailable", 503)

        upload, outcome = self._assess(scan, self._client(metrics=down, project=NOT_ANALYSED))

        upload.assert_not_called()
        assert isinstance(outcome, RetryLaterError)
        assert self._row_kept(scan)

    def test_a_failed_project_read_is_not_read_as_a_lost_upload(self, scan) -> None:
        """The metrics answer empty, then the project read fails: DT has not said
        whether it analysed the upload, so the version stays on record."""
        down = DependencyTrackAPIError("Dependency Track error (503): Service Unavailable", 503)

        upload, outcome = self._assess(scan, self._client(metrics={}, project=down))

        upload.assert_not_called()
        assert isinstance(outcome, RetryLaterError)
        assert self._row_kept(scan)

    def test_an_analysed_version_is_read_not_uploaded(self, scan) -> None:
        """The hourly rescan of a healthy SBOM, whose upload is weeks old."""
        upload, outcome = self._assess(scan, self._client(metrics={}, project=ANALYSED))

        upload.assert_not_called()
        assert outcome.summary.total_findings == 0
        assert self._row_kept(scan)

    def test_a_rerun_a_person_asked_for_uploads_again(self, scan) -> None:
        """Left alone, an analysed version is read as it stands: the result they
        asked to replace."""
        upload, outcome = self._assess(
            scan, self._client(metrics={}, project=ANALYSED), SBOMContext(rerun_requested=True)
        )

        upload.assert_called_once()
        assert isinstance(outcome, RetryLaterError)
        assert not self._row_kept(scan)

    def test_a_requested_rerun_keeps_the_version_on_another_server(self, scan) -> None:
        """Release tags reach a project through its record, so one on a server
        this run does not use has to outlive it."""
        from sbomify.apps.vulnerability_scanning.models import (
            DependencyTrackServer,
            SbomDependencyTrackProjectVersion,
        )

        other = DependencyTrackServer.objects.create(
            name="DT Other Server", url="https://dt-other.example.com", api_key="key", health_status="healthy"
        )
        elsewhere = SbomDependencyTrackProjectVersion.objects.create(
            sbom=scan.sbom,
            dt_server=other,
            dt_project_version=str(scan.sbom.id),
            dt_project_version_uuid=uuid.uuid4(),
        )

        self._assess(scan, self._client(metrics={}, project=ANALYSED), SBOMContext(rerun_requested=True))

        assert not self._row_kept(scan)
        assert SbomDependencyTrackProjectVersion.objects.filter(pk=elsewhere.pk).exists()

    def test_a_requested_rerun_of_an_sbom_no_longer_tracked_polls_what_it_has(self, scan) -> None:
        """A newer SBOM replaced it. Its upload keeps being read, but it is not sent
        to Dependency Track again: only tracked SBOMs are."""
        from sbomify.apps.sboms.models import SBOM

        SBOM.objects.create(name="s", version="2", component=scan.sbom.component, format="cyclonedx", format_version="1.6")

        upload, outcome = self._assess(
            scan, self._client(metrics={}, project=ANALYSED), SBOMContext(rerun_requested=True)
        )

        upload.assert_not_called()
        assert outcome.summary.total_findings == 0
        assert self._row_kept(scan)

    def _with_token(self, scan, processing: dict) -> MagicMock:
        scan.row.dt_upload_token = uuid.uuid4()
        scan.row.save(update_fields=["dt_upload_token"])
        client = self._client(metrics={"vulnerabilities": 0}, project=ANALYSED)
        client.get_upload_processing.return_value = processing
        return client

    def test_an_upload_dt_says_it_is_processing_after_a_day_is_uploaded_again(self, scan) -> None:
        upload, outcome = self._assess(scan, self._with_token(scan, {"processing": True, "status": "PENDING"}))

        upload.assert_called_once()
        assert isinstance(outcome, RetryLaterError)
        assert not self._row_kept(scan)


    def test_an_upload_dt_is_processing_since_today_keeps_waiting(self, scan) -> None:
        scan.row.last_sbom_upload = timezone.now() - timedelta(hours=6)
        scan.row.save(update_fields=["last_sbom_upload"])

        upload, outcome = self._assess(scan, self._with_token(scan, {"processing": True, "status": "RUNNING"}))

        upload.assert_not_called()
        assert isinstance(outcome, RetryLaterError)
        assert "still processing" in str(outcome)
        assert self._row_kept(scan)

    def test_an_upload_dt_failed_to_process_is_reported_then_uploaded_at_the_next_scan(self, scan) -> None:
        """DT 5 reports FAILED and stops. Reading the project then would return the
        previous upload's findings, or none, and the same BOM sent again at once
        would fail the same way on every poll."""
        scan.row.last_sbom_upload = timezone.now() - timedelta(minutes=5)
        scan.row.save(update_fields=["last_sbom_upload"])
        client = self._with_token(scan, {"processing": False, "status": "FAILED"})

        upload, outcome = self._assess(scan, client)

        upload.assert_not_called()
        client.get_project_vulnerabilities.assert_not_called()
        assert outcome.summary.error_count == 1
        assert "could not process this SBOM" in outcome.findings[0].description
        assert not self._row_kept(scan)

        upload, outcome = self._assess(scan, client)

        upload.assert_called_once()
        assert isinstance(outcome, RetryLaterError)
        assert "uploaded" in str(outcome)
