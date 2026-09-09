"""The vulnerabilities page and the scan agree about what is still open.

The page built its own package-and-alias merge straight off the stored
findings and never consulted VEX, so an advisory the scan had cleared rendered
as live. Yocto is how it surfaced: its SBOMs carry their own VEX, a
`security_VexFixedVulnAssessmentRelationship` stores as `analysis_state
"resolved"`, and the 6.0.3 release SBOM listed CVE-2026-59890 as a live HIGH
on a build that had patched it.

Suppressed advisories stay in the list, marked, because listing advisories is
this page's whole job. What changes is that they no longer count as open.
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

SETUPTOOLS = {"name": "setuptools", "version": "82.0.1", "ecosystem": "PyPI", "purl": "pkg:pypi/setuptools@82.0.1"}


def _finding(advisory_id: str, aliases: list[str], *, analysis_state: str | None = None) -> dict[str, Any]:
    finding = {
        "id": advisory_id,
        "title": f"{advisory_id} in setuptools",
        "description": "…",
        "severity": "high",
        "aliases": aliases,
        "component": dict(SETUPTOOLS),
    }
    if analysis_state:
        finding["analysis_state"] = analysis_state
    return finding


def _result(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "summary": {"total_findings": len(findings), "by_severity": {"high": len(findings)}},
        "findings": findings,
        "metadata": {"scanner": "osv-scanner"},
    }


@pytest.mark.django_db
class TestASuppressedAdvisoryIsNotListedAsLive:
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
    def _scanned(component: Component, findings: list[dict[str, Any]]) -> SBOM:
        sbom = SBOM.objects.create(
            component=component,
            name="core-image-minimal",
            format="spdx",
            format_version="3.0.1",
            version="",
            sbom_filename="x.json",
        )
        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            plugin_version="1.0.0",
            plugin_config_hash="0" * 64,
            category="security",
            run_reason=RunReason.ON_UPLOAD.value,
            status="completed",
            result=_result(findings),
        )
        return sbom

    @staticmethod
    def _packages(client: Client, sbom: SBOM):
        response = client.get(reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sbom.id}))
        assert response.status_code == 200
        data = response.context["vulnerabilities"]
        assert data and data.get("results"), "the page listed no packages at all"
        return data["results"][0]["packages"]

    def test_a_cleared_advisory_does_not_count_as_open(self, signed_in: tuple[Client, Component]) -> None:
        """Both ids of one advisory, both cleared by the document's own VEX."""
        client, component = signed_in
        sbom = self._scanned(
            component,
            [
                _finding("PYSEC-2026-3447", ["CVE-2026-59890", "GHSA-h35f-9h28-mq5c"], analysis_state="resolved"),
                _finding("GHSA-h35f-9h28-mq5c", ["CVE-2026-59890", "PYSEC-2026-3447"], analysis_state="resolved"),
            ],
        )

        package = self._packages(client, sbom)[0]

        assert package["open_count"] == 0, "a cleared advisory was counted as open"
        assert package["suppressed_count"] == 1
        assert package["vulnerabilities"][0]["vex_suppressed"] is True

    def test_it_is_still_listed_rather_than_hidden(self, signed_in: tuple[Client, Component]) -> None:
        """The page's job is the advisory list, so a cleared one stays, marked."""
        client, component = signed_in
        sbom = self._scanned(component, [_finding("CVE-2026-59890", [], analysis_state="resolved")])

        package = self._packages(client, sbom)[0]

        assert len(package["vulnerabilities"]) == 1
        assert package["vulnerabilities"][0]["id"] == "CVE-2026-59890"

    def test_a_live_advisory_still_counts(self, signed_in: tuple[Client, Component]) -> None:
        """The guard against a fix that suppresses everything."""
        client, component = signed_in
        sbom = self._scanned(component, [_finding("CVE-2026-11111", [])])

        package = self._packages(client, sbom)[0]

        assert package["open_count"] == 1
        assert package["suppressed_count"] == 0
        assert package["vulnerabilities"][0]["vex_suppressed"] is False

    def test_one_provider_still_calling_it_live_wins(self, signed_in: tuple[Client, Component]) -> None:
        """Folding two reports of one advisory must not lose the live one."""
        client, component = signed_in
        sbom = self._scanned(
            component,
            [
                _finding("PYSEC-2026-3447", ["CVE-2026-59890"], analysis_state="resolved"),
                _finding("CVE-2026-59890", ["PYSEC-2026-3447"]),
            ],
        )

        package = self._packages(client, sbom)[0]

        assert package["open_count"] == 1, "a live report was folded away by a suppressed one"
        assert package["vulnerabilities"][0]["vex_suppressed"] is False
