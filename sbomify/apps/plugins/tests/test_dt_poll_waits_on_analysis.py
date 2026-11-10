"""A Dependency Track scan is ready when DT's analysis is, not when its metrics are.

Dependency Track 4.14 stamps ``lastVulnerabilityAnalysis`` on the project when it
finishes analysing an uploaded BOM, and only then queues the metrics update as a
separate event. That event can wait behind every other project's metrics work, so a
poll that waits for metrics can run out of retries while the findings are already
there to read. The scan then shows "Could not scan".
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
from sbomify.apps.plugins.sdk.base import RetryLaterError

FINDING = {
    "vulnerability": {"vulnId": "CVE-2021-44228", "severity": "CRITICAL", "description": "rce"},
    "component": {
        "name": "log4j-core",
        "version": "2.14.1",
        "purl": "pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1",
    },
}


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
