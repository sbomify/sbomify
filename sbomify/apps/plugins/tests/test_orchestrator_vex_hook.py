"""Scan-time VEX annotation in the orchestrator.

The hook is best-effort on top of a completed scan (a VEX problem must never
invalidate the scan result) and release-aware (a VEX pinned in a release that
contains the scanned SBOM wins over the component's latest VEX).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.plugins.orchestrator import PluginOrchestrator
from sbomify.apps.plugins.sdk import (
    AssessmentPlugin,
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
)
from sbomify.apps.plugins.sdk.base import SBOMContext
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team


class SecurityMockPlugin(AssessmentPlugin):
    """A security-category plugin returning two fixed findings."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="mock-security",
            version="1.0.0",
            category=AssessmentCategory.SECURITY,
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        return AssessmentResult(
            plugin_name="mock-security",
            plugin_version="1.0.0",
            category="security",
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(total_findings=2, by_severity={"high": 2}),
            findings=[
                Finding(
                    id="CVE-2026-1111",
                    title="foo vuln",
                    description="",
                    severity="high",
                    component={"name": "foo", "version": "1.0.0", "purl": "pkg:npm/foo@1.0.0"},
                ),
                Finding(
                    id="CVE-2026-2222",
                    title="bar vuln",
                    description="",
                    severity="high",
                    component={"name": "bar", "version": "2.0.0", "purl": "pkg:npm/bar@2.0.0"},
                ),
            ],
        )


def _vex_doc(cve: str, purl: str) -> bytes:
    return json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "components": [
                {"type": "library", "name": purl.split("/")[-1].split("@")[0], "purl": purl, "bom-ref": purl}
            ],
            "vulnerabilities": [
                {
                    "id": cve,
                    "analysis": {"state": "not_affected", "justification": "code_not_reachable"},
                    "affects": [{"ref": purl}],
                }
            ],
        }
    ).encode()


@pytest.fixture
def team(db) -> Team:
    BillingPlan.objects.get_or_create(
        key="community",
        defaults={"name": "Community", "max_products": 1, "max_components": 5, "max_users": 2},
    )
    return Team.objects.create(name="VEX Hook Team", billing_plan="community")


@pytest.fixture
def component(team: Team) -> Component:
    return Component.objects.create(team=team, name="vex-hook-component")


@pytest.fixture
def sbom(component: Component) -> SBOM:
    return SBOM.objects.create(
        name="scan-target",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="scan-target.json",
        component=component,
    )


@pytest.fixture
def scan_sbom_bytes() -> bytes:
    return json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "components": []}).encode()


@pytest.mark.django_db
class TestOrchestratorVexHook:
    def _run(self, sbom: SBOM, scan_sbom_bytes: bytes, mocker):
        mocker.patch(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            return_value=(sbom, scan_sbom_bytes),
        )
        return PluginOrchestrator().run_assessment(
            sbom_id=sbom.id,
            plugin=SecurityMockPlugin(),
            run_reason=RunReason.ON_UPLOAD,
        )

    def test_component_vex_annotates_scan(self, sbom, scan_sbom_bytes, mocker):
        """The component's VEX suppresses matching findings at scan time."""
        SBOM.objects.create(
            name="vex",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="component.vex.json",
            component=sbom.component,
            bom_type=SBOM.BomType.VEX,
        )
        s3 = mocker.patch("sbomify.apps.core.object_store.StorageClient")
        s3.return_value.get_sbom_data.return_value = _vex_doc("CVE-2026-1111", "pkg:npm/foo@1.0.0")

        run = self._run(sbom, scan_sbom_bytes, mocker)

        assert run.status == RunStatus.COMPLETED.value
        assert run.result["summary"]["suppressed_count"] == 1
        assert run.result["summary"]["total_findings"] == 1
        states = {f["id"]: f.get("analysis_state") for f in run.result["findings"]}
        assert states["CVE-2026-1111"] == "not_affected"
        assert states["CVE-2026-2222"] is None

    def test_vex_load_failure_keeps_scan_result(self, sbom, scan_sbom_bytes, mocker):
        """An S3 failure while loading the VEX must not fail a completed scan."""
        SBOM.objects.create(
            name="vex",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="component.vex.json",
            component=sbom.component,
            bom_type=SBOM.BomType.VEX,
        )
        s3 = mocker.patch("sbomify.apps.core.object_store.StorageClient")
        s3.return_value.get_sbom_data.side_effect = RuntimeError("S3 unavailable")

        run = self._run(sbom, scan_sbom_bytes, mocker)

        assert run.status == RunStatus.COMPLETED.value
        assert run.result["summary"]["total_findings"] == 2
        assert run.result["summary"].get("suppressed_count") in (0, None)

    def test_release_slot_vex_wins_over_component_latest(self, sbom, scan_sbom_bytes, mocker):
        """A VEX pinned in a release containing the scanned SBOM outranks the
        component's newer latest VEX."""
        component = sbom.component
        release_vex = SBOM.objects.create(
            name="release-vex",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="release.vex.json",
            component=component,
            bom_type=SBOM.BomType.VEX,
        )
        SBOM.objects.create(
            name="latest-vex",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename="latest.vex.json",
            component=component,
            bom_type=SBOM.BomType.VEX,
        )
        product = Product.objects.create(team=component.team, name="vex-hook-product")
        release = Release.objects.create(product=product, name="v1")
        ReleaseArtifact.objects.create(release=release, sbom=sbom)
        ReleaseArtifact.objects.create(release=release, sbom=release_vex)

        def by_filename(filename: str):
            if filename == "release.vex.json":
                return _vex_doc("CVE-2026-1111", "pkg:npm/foo@1.0.0")
            return _vex_doc("CVE-2026-2222", "pkg:npm/bar@2.0.0")

        s3 = mocker.patch("sbomify.apps.core.object_store.StorageClient")
        s3.return_value.get_sbom_data.side_effect = by_filename

        run = self._run(sbom, scan_sbom_bytes, mocker)

        assert run.status == RunStatus.COMPLETED.value
        states = {f["id"]: f.get("analysis_state") for f in run.result["findings"]}
        assert states["CVE-2026-1111"] == "not_affected"
        assert states["CVE-2026-2222"] is None
