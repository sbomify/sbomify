"""The artifact page's vulnerability card, when every scanner declined.

A skipped run contributes no vulnerabilities and zero severity counts, exactly
as a clean scan does. The stored result is not empty: it carries bookkeeping of
its own, a status finding naming the reason and the counts that go with it, and
``metadata.skipped`` is what marks it. None of that bookkeeping is a
vulnerability, so none of it reaches the numbers on the card. The internal
tables already tell the two apart.
The card at the top of the artifact page did not: it read the latest completed
security runs whatever they were, so an SPDX 3 document that OSV and Dependency
Track had both refused rendered as

    Vulnerability Scan  8 Sep 2026  DEPENDENCY-TRACK, OSV
    0 total findings    0 CRITICAL  0 HIGH  0 MEDIUM  0 LOW

which is what a clean scan looks like.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
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


def _skipped(total_findings: int) -> dict[str, Any]:
    """A skipped result as the plugins actually store one.

    Two shapes are in production and the count is what differs.
    ``build_single_finding_result`` in the SDK sets total_findings to 0 on
    purpose, so a skip does not read as "1 finding"; OSV's no-packages skip
    builds its own summary and sets 1. Both carry the status finding and
    metadata.skipped, which is what this card reads, so both belong here.
    """
    return {
        "summary": {"total_findings": total_findings, "warning_count": 1},
        "findings": [
            {
                "id": "osv:no-packages",
                "title": "No Packages Recognised",
                "status": "warning",
                "severity": "info",
            }
        ],
        "metadata": {"scanner": "osv-scanner", "skipped": True, "no_packages": True},
    }


SKIPPED_RESULT: dict[str, Any] = _skipped(0)
CLEAN_RESULT: dict[str, Any] = {
    "summary": {"total_findings": 0, "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0}},
    "findings": [],
    "metadata": {"scanner": "osv-scanner"},
}


def _run(sbom: SBOM, plugin_name: str, result: dict[str, Any], created_at: datetime | None = None) -> AssessmentRun:
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin_name,
        plugin_version="1.0.0",
        plugin_config_hash=sha256(plugin_name.encode()).hexdigest(),
        category="security",
        run_reason=RunReason.ON_UPLOAD.value,
        status="completed",
        result=result,
    )
    if created_at is not None:
        # created_at is auto_now_add, so it has to be written back.
        AssessmentRun.objects.filter(pk=run.pk).update(created_at=created_at)
        run.refresh_from_db()
    return run


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

    @pytest.mark.parametrize("total_findings", [0, 1], ids=["sdk-shape", "osv-shape"])
    def test_every_scanner_skipping_leaves_no_scan_to_summarise(
        self, signed_in: tuple[Client, Component], total_findings: int
    ) -> None:
        """Both counts a skip is stored with. metadata.skipped is the marker,
        and neither shape may reach the card."""
        client, component = signed_in
        sbom = self._sbom(component)
        _run(sbom, "osv", _skipped(total_findings))
        _run(sbom, "dependency-track", _skipped(total_findings))

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

    def test_the_date_comes_from_the_scan_it_reports_not_from_a_later_skip(
        self, signed_in: tuple[Client, Component]
    ) -> None:
        """A skip that lands after a real scan must not lend it its timestamp."""
        client, component = signed_in
        sbom = self._sbom(component)
        scanned_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        _run(sbom, "osv", CLEAN_RESULT, created_at=scanned_at)
        _run(sbom, "dependency-track", SKIPPED_RESULT, created_at=scanned_at + timedelta(days=3))

        summary = self._summary(client, component, sbom)
        assert summary is not None
        assert summary["provider"] == "osv"
        assert summary["scan_date"] == scanned_at

    def test_a_scanner_that_ran_is_not_hidden_by_one_that_skipped(self, signed_in: tuple[Client, Component]) -> None:
        client, component = signed_in
        sbom = self._sbom(component)
        _run(sbom, "dependency-track", SKIPPED_RESULT)
        _run(sbom, "osv", CLEAN_RESULT)

        summary = self._summary(client, component, sbom)
        assert summary is not None
        assert summary["provider"] == "osv"
