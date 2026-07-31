"""The product page's components-and-security rows must mirror the component
page's merged, VEX-aware severity math and sort worst-first."""

from __future__ import annotations

import pytest

from sbomify.apps.core.models import Component, Release
from sbomify.apps.core.services.product_page import build_product_components_rows, build_product_releases_summary
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM, Product

pytestmark = pytest.mark.django_db


def _make_scan(sbom: SBOM, findings: list[dict], plugin: str = "osv") -> AssessmentRun:
    by_severity: dict[str, int] = {}
    for f in findings:
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        category="security",
        status="completed",
        result={"findings": findings, "summary": {"total_findings": len(findings), "by_severity": by_severity}},
    )


def test_rows_sort_worst_first_with_rollup(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    product = Product.objects.create(name="prod", team=team)

    clean = Component.objects.create(name="clean-comp", team=team)
    risky = Component.objects.create(name="a-risky-comp", team=team)
    unscanned = Component.objects.create(name="unscanned-comp", team=team)
    for component in (clean, risky, unscanned):
        product.components.add(component)

    clean_sbom = SBOM.objects.create(name="s1", component=clean, version="1.0", format="cyclonedx")
    risky_sbom = SBOM.objects.create(name="s2", component=risky, version="2.0", format="cyclonedx")
    _make_scan(clean_sbom, [])
    _make_scan(
        risky_sbom,
        [
            {"id": "CVE-1", "severity": "critical", "component": {"name": "p", "version": "1"}},
            {"id": "CVE-2", "severity": "medium", "component": {"name": "p", "version": "1"}},
        ],
    )

    data = build_product_components_rows(product.id)
    names = [r["name"] for r in data["rows"]]
    assert names == ["a-risky-comp", "clean-comp", "unscanned-comp"]

    by_name = {r["name"]: r for r in data["rows"]}
    assert by_name["a-risky-comp"]["status"] == "critical"
    assert by_name["a-risky-comp"]["vuln"]["critical"] == 1
    assert by_name["clean-comp"]["status"] == "clean"
    assert by_name["unscanned-comp"]["status"] == "not_scanned"
    assert by_name["unscanned-comp"]["vuln"] is None
    assert data["rollup"] == {"total": 2, "critical": 1, "high": 0, "medium": 1, "low": 0}


def test_releases_summary_lists_newest_with_latest_first(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    product = Product.objects.create(name="prod2", team=team)
    assert build_product_releases_summary(product.id) == {"total": 0, "releases": []}

    Release.objects.create(product_id=product.id, name="v1.0")
    latest = Release.objects.create(product_id=product.id, name="latest", is_latest=True)

    summary = build_product_releases_summary(product.id)
    assert summary["total"] == 2
    assert [r["name"] for r in summary["releases"]] == ["latest", "v1.0"]
    assert summary["releases"][0]["id"] == latest.id
    assert summary["releases"][0]["is_latest"] is True
    assert summary["releases"][0]["artifact_count"] == 0

    for i in range(6):
        Release.objects.create(product_id=product.id, name=f"v2.{i}")
    capped = build_product_releases_summary(product.id)
    assert capped["total"] == 8
    assert len(capped["releases"]) == 2
    assert capped["releases"][0]["name"] == "latest"
