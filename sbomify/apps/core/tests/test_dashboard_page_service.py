"""The dashboard digest must mirror the component drill-down's merged,
VEX-aware severity math: worst first, suppressed findings excluded."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from sbomify.apps.core.models import Component
from sbomify.apps.core.services.dashboard_page import build_dashboard_context
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM

pytestmark = pytest.mark.django_db


def _make_scan(sbom: SBOM, findings: list[dict], plugin: str = "osv") -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        category="security",
        status="completed",
        result={"findings": findings, "summary": {"total_findings": len(findings)}},
    )


def _finding(advisory: str, severity: str, cvss: float | None = None, state: str = "") -> dict:
    row: dict = {"id": advisory, "severity": severity, "component": {"name": "pkg", "version": "1.0"}}
    if cvss is not None:
        row["cvss_score"] = cvss
    if state:
        row["analysis_state"] = state
    return row


def test_first_visit_when_no_artifacts(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    Component.objects.create(name="empty", team=team)
    cache.clear()

    context = build_dashboard_context(team.id)

    assert context["is_first_visit"] is True
    assert context["needs_attention"] == []


def test_digest_ranks_worst_first_and_excludes_suppressed(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    component = Component.objects.create(name="api", team=team)
    sbom = SBOM.objects.create(name="s", component=component, version="1.0", format="cyclonedx")
    _make_scan(
        sbom,
        [
            _finding("CVE-MEDIUM", "medium"),
            _finding("CVE-CRIT-LOW-SCORE", "critical", cvss=7.0),
            _finding("CVE-CRIT-HIGH-SCORE", "critical", cvss=9.8),
            _finding("CVE-SUPPRESSED", "critical", cvss=10.0, state="not_affected"),
            _finding("CVE-HIGH", "high"),
        ],
    )
    cache.clear()

    context = build_dashboard_context(team.id)

    assert context["is_first_visit"] is False
    ids = [f["id"] for f in context["needs_attention"]]
    assert ids == ["CVE-CRIT-HIGH-SCORE", "CVE-CRIT-LOW-SCORE", "CVE-HIGH"]  # capped at 3, suppressed absent
    top = context["needs_attention"][0]
    assert top["component_id"] == component.id
    assert top["component_name"] == "api"
    assert top["sbom_version"] == "1.0"


def test_digest_uses_latest_sbom_only(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    component = Component.objects.create(name="api", team=team)
    old = SBOM.objects.create(name="s", component=component, version="0.9", format="cyclonedx")
    new = SBOM.objects.create(name="s", component=component, version="1.0", format="cyclonedx")
    _make_scan(old, [_finding("CVE-OLD", "critical")])
    _make_scan(new, [_finding("CVE-NEW", "high")])
    cache.clear()

    context = build_dashboard_context(team.id)

    ids = [f["id"] for f in context["needs_attention"]]
    assert ids == ["CVE-NEW"]  # the superseded SBOM's findings don't resurface


def test_digest_recency_breaks_ties_within_severity(sample_team_with_owner_member):
    """Two criticals in different components: the freshly-scanned component leads."""
    from datetime import timedelta

    from django.utils import timezone

    team = sample_team_with_owner_member.team
    stale = Component.objects.create(name="stale", team=team)
    fresh = Component.objects.create(name="fresh", team=team)
    stale_sbom = SBOM.objects.create(name="s", component=stale, version="1.0", format="cyclonedx")
    fresh_sbom = SBOM.objects.create(name="s", component=fresh, version="2.0", format="cyclonedx")
    old_run = _make_scan(stale_sbom, [_finding("CVE-STALE", "critical", cvss=10.0)])
    AssessmentRun.objects.filter(pk=old_run.pk).update(created_at=timezone.now() - timedelta(days=30))
    _make_scan(fresh_sbom, [_finding("CVE-FRESH", "critical", cvss=7.0)])
    cache.clear()

    context = build_dashboard_context(team.id)

    ids = [f["id"] for f in context["needs_attention"]]
    assert ids == ["CVE-FRESH", "CVE-STALE"]  # recency outranks CVSS inside the severity band
