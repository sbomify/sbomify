"""The dashboard digest must mirror the component drill-down's merged,
VEX-aware severity math: worst first, suppressed findings excluded."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from pytest_mock import MockerFixture

from sbomify.apps.core.models import Component
from sbomify.apps.core.services.dashboard_page import build_dashboard_context
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _make_scan(sbom: SBOM, findings: list[dict], plugin: str = "osv") -> AssessmentRun:
    """A completed run, projected into the findings table the way one really is.

    The digest reads that table now. In production nothing creates a completed
    run without the orchestrator, which calls ``sync_findings_safely`` as part
    of finishing it, so a fixture that writes the row and stops is not a state
    the application can be in.
    """
    from sbomify.apps.vulnerability_scanning.findings import sync_findings

    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        category="security",
        status="completed",
        result={"findings": findings, "summary": {"total_findings": len(findings)}},
    )
    sync_findings(run)
    return run


def _finding(advisory: str, severity: str, cvss: float | None = None, state: str = "") -> dict:
    row: dict = {"id": advisory, "severity": severity, "component": {"name": "pkg", "version": "1.0"}}
    if cvss is not None:
        row["cvss_score"] = cvss
    if state:
        row["analysis_state"] = state
    return row


def test_first_visit_when_no_artifacts(sample_team_with_owner_member: Member) -> None:
    team = sample_team_with_owner_member.team
    Component.objects.create(name="empty", team=team)
    cache.clear()

    result = build_dashboard_context(team.id)
    assert result.ok
    context = result.value
    assert context is not None

    assert context["is_first_visit"] is True
    assert context["needs_attention"] == []


def test_digest_ranks_worst_first_and_excludes_suppressed(sample_team_with_owner_member: Member) -> None:
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

    result = build_dashboard_context(team.id)
    assert result.ok
    context = result.value
    assert context is not None

    assert context["is_first_visit"] is False
    ids = [f["id"] for f in context["needs_attention"]]
    assert ids == ["CVE-CRIT-HIGH-SCORE", "CVE-CRIT-LOW-SCORE", "CVE-HIGH", "CVE-MEDIUM"]
    top = context["needs_attention"][0]
    assert top["component_id"] == component.id
    assert top["component_name"] == "api"
    assert top["sbom_version"] == "1.0"


def test_digest_uses_latest_sbom_only(sample_team_with_owner_member: Member) -> None:
    team = sample_team_with_owner_member.team
    component = Component.objects.create(name="api", team=team)
    old = SBOM.objects.create(name="s", component=component, version="0.9", format="cyclonedx")
    new = SBOM.objects.create(name="s", component=component, version="1.0", format="cyclonedx")
    _make_scan(old, [_finding("CVE-OLD", "critical")])
    _make_scan(new, [_finding("CVE-NEW", "high")])
    cache.clear()

    result = build_dashboard_context(team.id)
    assert result.ok
    context = result.value
    assert context is not None

    ids = [f["id"] for f in context["needs_attention"]]
    assert ids == ["CVE-NEW"]  # the superseded SBOM's findings don't resurface


def test_digest_recency_breaks_ties_within_severity(sample_team_with_owner_member: Member) -> None:
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

    result = build_dashboard_context(team.id)
    assert result.ok
    context = result.value
    assert context is not None

    ids = [f["id"] for f in context["needs_attention"]]
    assert ids == ["CVE-FRESH", "CVE-STALE"]  # recency outranks CVSS inside the severity band


def test_overview_counts_latest_provider_results_and_scopes_products(sample_team_with_owner_member: Member) -> None:
    from sbomify.apps.core.models import Product
    from sbomify.apps.teams.models import Team

    workspace = sample_team_with_owner_member.team
    component = Component.objects.create(name="shared", team=workspace)
    sbom = SBOM.objects.create(name="s", component=component, version="1.0", format="cyclonedx")
    finding = _finding("CVE-SHARED", "critical")
    _make_scan(sbom, [finding])
    _make_scan(sbom, [finding], plugin="second-provider")
    for name in ("First", "Second"):
        product = Product.objects.create(name=name, team=workspace)
        product.components.add(component)
    other_workspace = Team.objects.create(name="Other")
    Product.objects.create(name="Hidden", team=other_workspace)
    cache.clear()

    result = build_dashboard_context(workspace.id)
    assert result.ok and result.value is not None
    assert result.value["metrics"]["open"] == 1
    assert result.value["metrics"]["critical_high"] == 1
    assert [row["name"] for row in result.value["products"]] == ["First", "Second"]
    assert [row["counts"]["total"] for row in result.value["products"]] == [1, 1]


def test_overview_unassessed_and_summary_only_results(sample_team_with_owner_member: Member) -> None:
    from sbomify.apps.core.models import Product

    workspace = sample_team_with_owner_member.team
    Component.objects.create(name="missing", team=workspace)
    component = Component.objects.create(name="summary", team=workspace)
    product = Product.objects.create(name="Summary product", team=workspace)
    product.components.add(component)
    sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="summary-provider",
        category="security",
        status="completed",
        result={"summary": {"total_findings": 7, "by_severity": {"critical": 2, "high": 3}}},
    )
    cache.clear()

    result = build_dashboard_context(workspace.id)
    assert result.ok and result.value is not None
    assert result.value["unassessed"] == 1
    assert result.value["metrics"]["open"] == 7
    assert result.value["products"][0]["counts"]["unknown"] == 2
    assert result.value["needs_attention"] == []


def test_overview_freshness_honours_component_override(sample_team_with_owner_member: Member) -> None:
    from datetime import timedelta

    from django.utils import timezone

    workspace = sample_team_with_owner_member.team
    workspace.sbom_freshness_days = 30
    workspace.save(update_fields=["sbom_freshness_days"])
    for name, override in (("stale", None), ("fresh", 90)):
        component = Component.objects.create(name=name, team=workspace, sbom_freshness_days=override)
        sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
        SBOM.objects.filter(id=sbom.id).update(created_at=timezone.now() - timedelta(days=45))
    cache.clear()

    result = build_dashboard_context(workspace.id)
    assert result.ok and result.value is not None
    assert result.value["metrics"]["stale"] == 1


def test_overview_kev_priority_keeps_suppressed_findings_out(
    sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    mocker.patch(
        "sbomify.apps.vulnerability_scanning.kev.kev_ids_for_serialization", return_value=frozenset({"cve-kev"})
    )
    workspace = sample_team_with_owner_member.team
    component = Component.objects.create(name="api", team=workspace)
    sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx")
    _make_scan(
        sbom,
        [
            _finding("CVE-CRITICAL", "critical"),
            _finding("CVE-KEV", "high"),
            _finding("CVE-CLEARED", "critical", state="not_affected"),
        ],
    )
    cache.clear()

    result = build_dashboard_context(workspace.id)
    assert result.ok and result.value is not None
    assert result.value["needs_attention"][0]["id"] == "CVE-KEV"
    assert result.value["metrics"]["open"] == 2
    assert result.value["metrics"]["known_exploited"] == 1


def test_document_only_workspace_is_not_empty(sample_team_with_owner_member: Member) -> None:
    from sbomify.apps.documents.models import Document

    workspace = sample_team_with_owner_member.team
    component = Component.objects.create(name="documents", team=workspace, component_type="document")
    Document.objects.create(name="Architecture", component=component)
    cache.clear()

    result = build_dashboard_context(workspace.id)
    assert result.ok and result.value is not None
    assert result.value["is_first_visit"] is False
    assert result.value["metrics"]["open"] == 0
    assert result.value["unassessed"] == 0


def test_overview_and_inventory_agree_on_product_evidence(sample_team_with_owner_member: Member) -> None:
    from sbomify.apps.core.models import Product
    from sbomify.apps.core.services.inventory_page import build_inventory_snapshot

    workspace = sample_team_with_owner_member.team
    document = Component.objects.create(name="Document", team=workspace, component_type="document")
    missing = Component.objects.create(name="Missing SBOM", team=workspace)
    no_policy = Component.objects.create(name="No policy", team=workspace)
    configured = Component.objects.create(name="With policy", team=workspace, sbom_freshness_days=30)
    for component in (no_policy, configured):
        _make_scan(SBOM.objects.create(name="bom", component=component, format="cyclonedx"), [])
    for name, assigned in (("Documents", [document]), ("Mixed", [document, missing, no_policy, configured])):
        Product.objects.create(name=name, team=workspace).components.add(*assigned)
    cache.clear()

    dashboard = build_dashboard_context(workspace.pk).value
    assert dashboard is not None
    inventory = {row["id"]: row for row in build_inventory_snapshot(workspace, "products")["rows"]}
    for row in dashboard["products"]:
        for field in ("component_count", "security_component_count", "unassessed", "stale", "missing_sboms", "no_policy"):
            assert row[field] == inventory[row["id"]][field], field
    assert dashboard["unassessed"] == 1
    mixed = next(row for row in dashboard["products"] if row["name"] == "Mixed")
    assert mixed["no_policy"] == 1
    assert mixed["missing_sboms"] == 1


def test_missing_workspace_returns_a_service_error() -> None:
    cache.clear()
    result = build_dashboard_context(987654321)
    assert not result.ok
    assert result.status_code == 404


def test_patch_sla_joins_alias_history_without_resetting_at_upload(
    sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    from datetime import timedelta

    from django.utils import timezone

    from sbomify.apps.core.models import Product
    from sbomify.apps.plugins.models import VulnerabilityLifecycle

    now = timezone.now()
    mocker.patch("sbomify.apps.core.services.security_snapshot.timezone.now", return_value=now)
    workspace = sample_team_with_owner_member.team
    component = Component.objects.create(name="shared", team=workspace)
    sbom = SBOM.objects.create(name="new upload", component=component, format="cyclonedx")
    overdue = {**_finding("CVE-OVERDUE", "high", state="in_triage"), "aliases": ["GHSA-EARLY"]}
    _make_scan(
        sbom,
        [
            overdue,
            _finding("CVE-NEW", "critical"),
            _finding("CVE-LOW", "low"),
            _finding("CVE-UNKNOWN", "medium"),
            _finding("CVE-SUPPRESSED", "critical", state="not_affected"),
        ],
    )
    for advisory, age, resolved in (
        ("GHSA-EARLY", 40, False),
        ("CVE-OVERDUE", 10, False),
        ("CVE-NEW", 1, False),
        ("CVE-UNKNOWN", 200, True),
        ("CVE-SUPPRESSED", 200, False),
    ):
        VulnerabilityLifecycle.objects.create(
            component=component,
            advisory_id=advisory,
            first_seen_at=now - timedelta(days=age),
            last_seen_at=now,
            resolved_at=now if resolved else None,
        )
    for name in ("First", "Second"):
        product = Product.objects.create(name=name, team=workspace)
        product.components.add(component)
    cache.clear()

    result = build_dashboard_context(workspace.id)
    assert result.ok and result.value is not None
    context = result.value
    rows = {row["id"]: row for row in context["needs_attention"]}
    assert context["needs_attention"][0]["id"] == "CVE-OVERDUE"
    assert rows["CVE-OVERDUE"]["sla"]["label"] == "10 days over"
    assert rows["CVE-OVERDUE"]["decision"] == "In triage"
    assert rows["CVE-OVERDUE"]["products"] == ["First", "Second"]
    assert rows["CVE-NEW"]["sla"]["label"] == "6 days left"
    assert rows["CVE-LOW"]["sla"]["label"] == "Best effort"
    assert rows["CVE-UNKNOWN"]["sla"]["label"] == "Awaiting history"
    assert context["metrics"]["past_sla"] == 1
    assert context["metrics"]["sla_unknown"] == 1
    assert [product["past_sla"] for product in context["products"]] == [1, 1]


def test_overview_evidence_distinguishes_missing_from_stale(sample_team_with_owner_member: Member) -> None:
    from datetime import timedelta

    from django.utils import timezone

    from sbomify.apps.core.models import Product

    workspace = sample_team_with_owner_member.team
    workspace.sbom_freshness_days = 30
    workspace.save(update_fields=["sbom_freshness_days"])
    product = Product.objects.create(name="Evidence", team=workspace)
    missing = Component.objects.create(name="missing", team=workspace)
    stale = Component.objects.create(name="stale", team=workspace)
    product.components.add(missing, stale)
    sbom = SBOM.objects.create(name="old", component=stale, format="cyclonedx")
    SBOM.objects.filter(pk=sbom.pk).update(created_at=timezone.now() - timedelta(days=45))
    cache.clear()

    result = build_dashboard_context(workspace.id)
    assert result.ok and result.value is not None
    assert result.value["products"][0]["missing_sboms"] == 1
    assert result.value["products"][0]["stale"] == 1
    assert result.value["release_products"] == [{"id": product.id, "name": "Evidence"}]
