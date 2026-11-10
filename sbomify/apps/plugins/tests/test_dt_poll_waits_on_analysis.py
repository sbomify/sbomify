"""A Dependency Track scan is ready when DT's analysis is, not when its metrics are.

Dependency Track 4.14 stamps ``lastVulnerabilityAnalysis`` on the project when it
finishes analysing an uploaded BOM, and only then queues the metrics update as a
separate event. That event can wait behind every other project's metrics work, so a
poll that waits for metrics can run out of retries while the findings are already
there to read. The scan then shows "Could not scan".
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin, _UploadFailed
from sbomify.apps.plugins.sdk.base import RetryLaterError
from sbomify.apps.vulnerability_scanning.clients import DependencyTrackAPIError

FINDING = {
    "vulnerability": {"vulnId": "CVE-2021-44228", "severity": "CRITICAL", "description": "rce"},
    "component": {
        "name": "log4j-core",
        "version": "2.14.1",
        "purl": "pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1",
    },
}

TOKEN = "01a1c50c-ec03-7209-be4a-8b4dac354c18"
ANALYSED = {"lastBomImport": 1762196390000, "lastVulnerabilityAnalysis": 1762196400000}


@pytest.mark.django_db
class TestPollWaitsOnAnalysis:
    @pytest.fixture
    def version_row(self):
        from sbomify.apps.core.models import Component
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.teams.models import Workspace
        from sbomify.apps.vulnerability_scanning.models import (
            DependencyTrackServer,
            SbomDependencyTrackProjectVersion,
        )

        team = Workspace.objects.create(name="DT Poll Team", key="dtpollteam", billing_plan="business")
        server = DependencyTrackServer.objects.create(
            name="DT Poll Server", url="https://dt-poll.example.com", api_key="key", health_status="healthy"
        )
        component = Component.objects.create(name="DT Poll Component", team=team)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", format_version="1.6")
        return SbomDependencyTrackProjectVersion.objects.create(
            sbom=sbom, dt_server=server, dt_project_version=str(sbom.id), dt_project_version_uuid=uuid.uuid4()
        )

    @staticmethod
    def _poll(version_row, client):
        return DependencyTrackPlugin()._poll_results(
            client=client,
            version_row=version_row,
            sbom_id=str(version_row.sbom_id),
            project_name="dev-sbomify-component",
            current_release_names=[],
        )

    @staticmethod
    def _client(project: dict | Exception) -> MagicMock:
        client = MagicMock()
        client.get_project_metrics.return_value = {}
        client.get_project_vulnerabilities.return_value = {"content": [FINDING]}
        if isinstance(project, Exception):
            client.get_project.side_effect = project
        else:
            client.get_project.return_value = project
        return client

    def test_a_finished_analysis_is_read_before_its_metrics_arrive(self, version_row) -> None:
        client = self._client({"lastBomImport": 1762196390000, "lastVulnerabilityAnalysis": 1762196400000})

        result = self._poll(version_row, client)

        assert result.summary.total_findings == 1
        assert result.findings[0].id == "CVE-2021-44228"

    def test_an_analysis_still_running_keeps_waiting(self, version_row) -> None:
        client = self._client({"lastBomImport": 1762196390000, "lastVulnerabilityAnalysis": None})

        with pytest.raises(RetryLaterError, match="still processing"):
            self._poll(version_row, client)

        client.get_project_vulnerabilities.assert_not_called()

    def test_a_project_dt_cannot_return_keeps_waiting(self, version_row) -> None:
        client = self._client(Exception("Dependency Track error (503): Service Unavailable"))

        with pytest.raises(RetryLaterError, match="still processing"):
            self._poll(version_row, client)

        client.get_project_vulnerabilities.assert_not_called()

    # Dependency Track 5.2.1, measured: metrics answer 0.05 s after an upload,
    # counting no vulnerabilities, while the upload's token still says PENDING,
    # and the finding arrives a second later. On a re-upload of the same version
    # the last analysis is still stamped on the project. Either way the checks
    # above read findings DT had not produced yet, so a row with a token waits
    # for DT to say it processed that upload.
    @pytest.fixture
    def uploaded_row(self, version_row):
        version_row.dt_upload_token = TOKEN
        version_row.save(update_fields=["dt_upload_token"])
        return version_row

    def _token_client(self, processing: dict | Exception, metrics: dict | None = None) -> MagicMock:
        client = self._client(ANALYSED)
        client.get_project_metrics.return_value = {"vulnerabilities": 0} if metrics is None else metrics
        if isinstance(processing, Exception):
            client.get_upload_processing.side_effect = processing
        else:
            client.get_upload_processing.return_value = processing
        return client

    @pytest.mark.parametrize(
        "processing",
        [{"processing": True}, {"processing": True, "status": "PENDING"}, {"processing": True, "status": "RUNNING"}],
    )
    def test_an_upload_dt_is_processing_waits_though_metrics_and_an_old_analysis_answer(
        self, uploaded_row, processing
    ) -> None:
        client = self._token_client(processing)

        with pytest.raises(RetryLaterError, match="still processing"):
            self._poll(uploaded_row, client)

        client.get_upload_processing.assert_called_once_with(TOKEN)
        client.get_project_vulnerabilities.assert_not_called()

    @pytest.mark.parametrize("processing", [{"processing": False}, {"processing": False, "status": "COMPLETED"}])
    def test_a_processed_upload_is_read_and_its_token_dropped(self, uploaded_row, processing) -> None:
        result = self._poll(uploaded_row, self._token_client(processing))

        assert result.summary.total_findings == 1
        uploaded_row.refresh_from_db()
        assert uploaded_row.dt_upload_token is None
        assert uploaded_row.last_metrics_sync is not None

    def test_a_token_dt_does_not_know_falls_back_to_the_project(self, uploaded_row) -> None:
        """DT 5 expires tokens and DT 4 forgets them on restart. Both then answer
        ``processing: false`` with no status, as DT 4 does for a finished upload,
        so the project's own state decides, as it does without a token."""
        client = self._token_client({"processing": False}, metrics={})
        client.get_project.return_value = {"lastBomImport": 1762196390000, "lastVulnerabilityAnalysis": None}

        with pytest.raises(RetryLaterError, match="still processing"):
            self._poll(uploaded_row, client)

        client.get_project_vulnerabilities.assert_not_called()

    def test_an_upload_dt_failed_to_process_is_not_read(self, uploaded_row) -> None:
        """DT 5 only. Its own exception, so the scan reports the failure where a
        lost upload is sent again at once."""
        client = self._token_client({"processing": False, "status": "FAILED"})

        with pytest.raises(_UploadFailed, match="failed to process"):
            self._poll(uploaded_row, client)

        client.get_project_vulnerabilities.assert_not_called()

    def test_a_token_dt_cannot_answer_for_keeps_waiting(self, uploaded_row) -> None:
        client = self._token_client(Exception("Dependency Track error (503): Service Unavailable"))

        with pytest.raises(RetryLaterError, match="still processing"):
            self._poll(uploaded_row, client)

        client.get_project_vulnerabilities.assert_not_called()

    def test_a_token_dt_still_cannot_answer_for_later_falls_back_to_the_project(self, uploaded_row) -> None:
        """A proxy that refuses the token endpoint fails every read. Waiting on
        it without end would hold the findings back for good."""
        uploaded_row.last_sbom_upload = timezone.now() - timedelta(hours=1)
        uploaded_row.save(update_fields=["last_sbom_upload"])
        client = self._token_client(Exception("Dependency Track error (503): Service Unavailable"))

        result = self._poll(uploaded_row, client)

        assert result.summary.total_findings == 1
        uploaded_row.refresh_from_db()
        assert uploaded_row.dt_upload_token is None

    def test_a_dt_without_the_token_endpoint_falls_back_to_the_project(self, uploaded_row) -> None:
        """A 404 will not turn into an answer on a later poll. Waiting on it
        would hold the findings back for good, so the project decides."""
        client = self._token_client(DependencyTrackAPIError("Dependency Track error (404)", status_code=404))

        result = self._poll(uploaded_row, client)

        assert result.summary.total_findings == 1
        uploaded_row.refresh_from_db()
        assert uploaded_row.dt_upload_token is None

    def test_without_a_token_dt_is_not_asked(self, version_row) -> None:
        """Rows uploaded before tokens were kept poll as they always did."""
        client = self._token_client({"processing": True})

        result = self._poll(version_row, client)

        assert result.summary.total_findings == 1
        client.get_upload_processing.assert_not_called()
