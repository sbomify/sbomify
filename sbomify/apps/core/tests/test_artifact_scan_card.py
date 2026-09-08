"""The artifact page's vulnerability card, when every scanner declined.

A skipped run stores zero findings exactly as a clean scan does. The internal
tables already tell the two apart. The card at the top of the artifact page did
not: it read the latest completed security runs whatever they were, so an SPDX 3
document that OSV and Dependency Track had both refused rendered as

    Vulnerability Scan  8 Sep 2026  DEPENDENCY-TRACK, OSV
    0 total findings    0 CRITICAL  0 HIGH  0 MEDIUM  0 LOW

which is what a clean scan looks like.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

SKIPPED_RESULT: dict[str, Any] = {
    "summary": {"total_findings": 1, "warning_count": 1},
    "findings": [{"id": "osv:no-packages", "title": "No Packages Recognised", "severity": "info"}],
    "metadata": {"scanner": "osv-scanner", "skipped": True, "no_packages": True},
}
CLEAN_RESULT: dict[str, Any] = {
    "summary": {"total_findings": 0, "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0}},
    "findings": [],
    "metadata": {"scanner": "osv-scanner"},
}


def _run(sbom: SBOM, plugin_name: str, result: dict[str, Any]) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin_name,
        plugin_version="1.0.0",
        category="security",
        status="completed",
        result=result,
    )


@pytest.mark.django_db
class TestTheScanCard:
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
            format_version="3.0.0",
            version="1.0",
            sbom_filename="x.json",
        )

    def _summary(self, client: Client, component: Component, sbom: SBOM):
        url = reverse(
            "core:component_item",
            kwargs={"component_id": component.id, "item_type": "sboms", "item_id": sbom.id},
        )
        response = client.get(url)
        assert response.status_code == 200
        return response.context["vulnerability_summary"]

    def test_every_scanner_skipping_leaves_no_scan_to_summarise(self, signed_in: tuple[Client, Component]) -> None:
        client, component = signed_in
        sbom = self._sbom(component)
        _run(sbom, "osv", SKIPPED_RESULT)
        _run(sbom, "dependency-track", SKIPPED_RESULT)

        assert self._summary(client, component, sbom) is None

    def test_a_real_clean_scan_still_reports_zero(self, signed_in: tuple[Client, Component]) -> None:
        """Zero findings is a fact when something was actually examined."""
        client, component = signed_in
        sbom = self._sbom(component)
        _run(sbom, "osv", CLEAN_RESULT)

        summary = self._summary(client, component, sbom)
        assert summary is not None
        assert summary["total"] == 0
        assert summary["provider"] == "osv"

    def test_a_scanner_that_ran_is_not_hidden_by_one_that_skipped(self, signed_in: tuple[Client, Component]) -> None:
        client, component = signed_in
        sbom = self._sbom(component)
        _run(sbom, "dependency-track", SKIPPED_RESULT)
        _run(sbom, "osv", CLEAN_RESULT)

        summary = self._summary(client, component, sbom)
        assert summary is not None
        assert summary["provider"] == "osv"
