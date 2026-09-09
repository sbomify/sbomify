"""A finding the scan suppressed must not be counted as a live vulnerability.

`extract_finding_rows` returns every finding, each carrying `vex_suppressed`,
because the drill-down table renders the suppressed ones marked as such. Three
tally sites then counted `len(rows)` without asking, so a finding the scan had
already cleared still landed in the card's total and its severity counts.

Yocto is how this surfaced. Its SBOMs carry their own VEX: a
`security_VexFixedVulnAssessmentRelationship` stores as `analysis_state
"resolved"`, which is in SUPPRESSED_STATES. On the Yocto 6.0.3 release SBOM the
stored run read `total_findings 0, suppressed_count 2` while the page above it
read `1 HIGH`, for the same run.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunReason
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

# Shaped after the real stored run for the Yocto 6.0.3 core-image-minimal SBOM:
# two ids for one advisory, both annotated "resolved" by the document's own VEX.
SUPPRESSED_RESULT: dict[str, Any] = {
    "summary": {
        "total_findings": 0,
        "suppressed_count": 2,
        "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
    },
    "findings": [
        {
            "id": "PYSEC-2026-3447",
            "title": "PYSEC-2026-3447",
            "severity": "high",
            "aliases": ["CVE-2026-59890", "GHSA-h35f-9h28-mq5c"],
            "component": {"name": "setuptools", "version": "82.0.1", "ecosystem": "PyPI"},
            "analysis_state": "resolved",
        },
        {
            "id": "GHSA-h35f-9h28-mq5c",
            "title": "setuptools: MANIFEST.in exclusion bypass",
            "severity": "high",
            "aliases": ["CVE-2026-59890", "PYSEC-2026-3447"],
            "component": {"name": "setuptools", "version": "82.0.1", "ecosystem": "PyPI"},
            "analysis_state": "resolved",
        },
    ],
    "metadata": {"scanner": "osv-scanner", "sbom_format": "spdx3", "converted_from": "SPDX-3.0"},
}

LIVE_RESULT: dict[str, Any] = {
    "summary": {"total_findings": 1, "by_severity": {"critical": 0, "high": 1, "medium": 0, "low": 0}},
    "findings": [
        {
            "id": "CVE-2026-11111",
            "title": "something genuinely open",
            "severity": "high",
            "component": {"name": "openssl", "version": "3.2.3", "ecosystem": "PyPI"},
        }
    ],
    "metadata": {"scanner": "osv-scanner"},
}


@pytest.mark.django_db
class TestTheCardCountsOnlyLiveFindings:
    @pytest.fixture
    def signed_in(self, sample_team_with_owner_member: Member) -> tuple[Client, Component]:
        component = Component.objects.create(
            team=sample_team_with_owner_member.team,
            name="yocto-image",
            component_type=Component.ComponentType.BOM,
        )
        client = Client()
        setup_authenticated_client_session(
            client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
        )
        return client, component

    @staticmethod
    def _sbom(component: Component) -> SBOM:
        return SBOM.objects.create(
            component=component,
            name="core-image-minimal",
            format="spdx",
            format_version="3.0.1",
            version="",
            sbom_filename="x.json",
        )

    @staticmethod
    def _run(sbom: SBOM, result: dict[str, Any]) -> AssessmentRun:
        return AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            plugin_version="1.0.0",
            plugin_config_hash="0" * 64,
            category="security",
            run_reason=RunReason.ON_UPLOAD.value,
            status="completed",
            result=result,
        )

    def _summary(self, client: Client, component: Component, sbom: SBOM):
        response = client.get(
            reverse(
                "core:component_item",
                kwargs={"component_id": component.id, "item_type": "sboms", "item_id": sbom.id},
            )
        )
        assert response.status_code == 200
        return response.context["vulnerability_summary"]

    def test_a_finding_the_scan_suppressed_is_not_counted(self, signed_in: tuple[Client, Component]) -> None:
        client, component = signed_in
        sbom = self._sbom(component)
        self._run(sbom, SUPPRESSED_RESULT)

        summary = self._summary(client, component, sbom)

        assert summary is not None
        assert summary["total"] == 0, "a suppressed finding was counted as a live vulnerability"
        assert summary["high"] == 0

    def test_a_live_finding_is_still_counted(self, signed_in: tuple[Client, Component]) -> None:
        """The guard against a fix that just zeroes the card."""
        client, component = signed_in
        sbom = self._sbom(component)
        self._run(sbom, LIVE_RESULT)

        summary = self._summary(client, component, sbom)

        assert summary is not None
        assert summary["total"] == 1
        assert summary["high"] == 1
