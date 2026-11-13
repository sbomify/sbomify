"""A Dependency Track scan reads its findings from the release-series tree.

sbomify no longer uploads one project per SBOM. The tree holds each tracked
SBOM in a project: a component in a live release, or its newest build. A scan
finds the project holding its SBOM and reads the findings from there. An SBOM
the tree has not taken yet waits for the tree's sync, and an SBOM sbomify no
longer tracks is not monitored.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
from sbomify.apps.plugins.models import TeamPluginSettings
from sbomify.apps.plugins.sdk.base import RetryLaterError
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.vulnerability_scanning.models import (
    DependencyTrackServer,
    DependencyTrackTreeProject,
    SbomDependencyTrackProjectVersion,
)

TREE = "sbomify.apps.vulnerability_scanning.services.dt_release_tree"
TASKS = "sbomify.apps.vulnerability_scanning.tasks"
FINDING = {
    "vulnerability": {"vulnId": "CVE-2021-44228", "severity": "CRITICAL", "description": "rce"},
    "component": {
        "name": "log4j-core",
        "version": "2.14.1",
        "purl": "pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1",
    },
}
ANALYSED = {"lastBomImport": 1762196390000, "lastVulnerabilityAnalysis": 1762196400000}


def _sbom(component: Component, version: str, fmt: str = "cyclonedx") -> SBOM:
    return SBOM.objects.create(
        name=component.name,
        version=version,
        component=component,
        format=fmt,
        format_version="1.6" if fmt == "cyclonedx" else "2.3",
        sbom_filename=f"{component.name}-{version}.json",
    )


@pytest.fixture
def scan(sample_team_with_owner_member, tmp_path):
    team = sample_team_with_owner_member.team
    TeamPluginSettings.objects.update_or_create(team=team, defaults={"enabled_plugins": ["dependency-track"]})
    server = DependencyTrackServer.objects.create(
        name="dt", url="https://dt.example.com", api_key="k", health_status="healthy"
    )
    component = Component.objects.create(name="auth", team=team)
    old = _sbom(component, "4.0.0")
    newest = _sbom(component, "4.1.0")
    path = tmp_path / "sbom.cdx.json"
    path.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1}))
    holder = DependencyTrackTreeProject.objects.create(
        dt_server=server,
        team=team,
        kind=DependencyTrackTreeProject.Kind.LATEST_COMPONENT,
        component=component,
        sbom=newest,
        dt_project_uuid=uuid.uuid4(),
        dt_name=f"test {team.key} · auth",
        dt_version="latest",
        dt_upload_token=uuid.uuid4(),
        last_bom_upload=timezone.now(),
    )
    return SimpleNamespace(
        team=team, server=server, component=component, old=old, sbom=newest, path=path, holder=holder
    )


def _client(*, metrics: dict | Exception | None = None, processing: dict | None = None) -> MagicMock:
    client = MagicMock()
    client.get_upload_processing.return_value = processing or {"processing": False}
    if isinstance(metrics, Exception):
        client.get_project_metrics.side_effect = metrics
    else:
        client.get_project_metrics.return_value = {"critical": 1} if metrics is None else metrics
    client.get_project.return_value = ANALYSED
    client.get_project_vulnerabilities.return_value = {"content": [FINDING]}
    return client


def _assess(scan, client: MagicMock, sbom: SBOM | None = None) -> object:
    with (
        patch.object(DependencyTrackPlugin, "_team_has_dt_enabled", return_value=True),
        patch(f"{TREE}.workspace_server", return_value=scan.server),
        patch("sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient", return_value=client),
    ):
        try:
            return DependencyTrackPlugin().assess(str((sbom or scan.sbom).id), scan.path)
        except RetryLaterError as retry:
            return retry


@pytest.mark.django_db
class TestScanFromTheTree:
    def test_findings_come_from_the_tree_project_holding_the_sbom(self, scan):
        client = _client()

        result = _assess(scan, client)

        assert result.summary.total_findings == 1
        client.get_project_vulnerabilities.assert_called_once_with(str(scan.holder.dt_project_uuid))
        client.upload_sbom.assert_not_called()
        client.upload_sbom_with_project_creation.assert_not_called()
        assert result.metadata["dt_project_name"] == scan.holder.dt_name

    def test_a_release_project_is_read_before_latest_builds(self, scan):
        release = DependencyTrackTreeProject.objects.create(
            dt_server=scan.server,
            team=scan.team,
            kind=DependencyTrackTreeProject.Kind.RELEASE_COMPONENT,
            component=scan.component,
            sbom=scan.sbom,
            dt_project_uuid=uuid.uuid4(),
            dt_name="release",
            dt_version="1.2",
        )
        client = _client()

        _assess(scan, client)

        client.get_project_vulnerabilities.assert_called_once_with(str(release.dt_project_uuid))

    def test_an_sbom_the_tree_has_not_taken_waits_and_asks_for_a_sync(self, scan, django_capture_on_commit_callbacks):
        scan.holder.delete()

        with (
            patch(f"{TASKS}.sync_dt_release_tree.send") as send,
            django_capture_on_commit_callbacks(execute=True),
        ):
            outcome = _assess(scan, _client())

        assert isinstance(outcome, RetryLaterError)
        send.assert_called_with(str(scan.team.id))

    def test_an_untracked_sbom_outside_the_tree_is_not_monitored(self, scan):
        result = _assess(scan, _client(), sbom=scan.old)

        assert result.findings[0].id == "dependency-track:not-tracked"

    def test_the_scan_handle_follows_the_sbom_to_the_project_now_holding_it(self, scan):
        SbomDependencyTrackProjectVersion.objects.create(
            sbom=scan.sbom, dt_server=scan.server, dt_project_version="old", dt_project_version_uuid=uuid.uuid4()
        )

        _assess(scan, _client())

        handle = SbomDependencyTrackProjectVersion.objects.get(sbom=scan.sbom, dt_server=scan.server)
        assert handle.dt_project_version_uuid == scan.holder.dt_project_uuid
        assert handle.dt_project_version == "latest"

    def test_a_spec_version_the_server_refused_is_a_skip_that_says_so(self, scan):
        DependencyTrackTreeProject.objects.filter(pk=scan.holder.pk).update(
            upload_refused="The BOM is invalid: unsupported specVersion 1.7"
        )
        client = _client()

        result = _assess(scan, client)

        assert result.findings[0].id == "dependency-track:unsupported-spec-version"
        assert "unsupported specVersion 1.7" in result.findings[0].description
        assert result.metadata.get("unsupported_input") is True
        client.get_project_vulnerabilities.assert_not_called()

    @pytest.mark.parametrize("imported, noted", [("CycloneDX 1.6", True), ("CycloneDX 1.7", False), (None, False)])
    def test_the_result_says_when_a_converted_copy_was_scanned(self, scan, imported, noted):
        scan.path.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.7", "version": 1}))
        client = _client()
        client.get_project.return_value = {**ANALYSED, "lastBomImportFormat": imported}

        result = _assess(scan, client)

        assert (result.metadata.get("converted_from") == "CycloneDX-1.7") is noted

    def test_an_spdx_sbom_that_cannot_become_cyclonedx_says_so(self, scan):
        spdx = _sbom(scan.component, "4.2.0", fmt="spdx")
        scan.path.write_text(json.dumps({"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT"}))

        with patch(
            "sbomify.apps.plugins.builtins.dependency_track.to_cyclonedx",
            side_effect=__import__("sbomify.apps.sboms.conversion", fromlist=["ConversionFailed"]).ConversionFailed(
                "no packages"
            ),
        ):
            result = _assess(scan, _client(), sbom=spdx)

        assert result.findings[0].id == "dependency-track:unsupported-format"
