"""The private component page's two security drill-downs.

The crypto half shows the fail/warning findings of the component's newest
crypto-bearing artifact: the newest CBOM when one exists, else the newest mixed
SBOM stamped ``has_crypto_assets=True`` (mixed documents keep ``bom_type=sbom``
so they retain NTIA and vulnerability assessment, but their crypto findings must
still surface here).

The vulnerability half builds the same page's findings panel, and is shared with
the HTMX endpoint the panel's own search, filters and pager call, so the first
render and every refresh of it resolve findings identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sbomify.apps.vulnerability_scanning.services.finding_browse import FindingQuery
from sbomify.apps.vulnerability_scanning.utils import SEVERITY_RANK


@dataclass(frozen=True)
class CbomIssuesContext:
    issues: list[dict[str, Any]] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    severities: list[str] = field(default_factory=list)
    artifact_version: str | None = None
    artifact_id: str | None = None
    # URL item_type of the artifact the issues came from: "cbom" for a CBOM
    # row, "sboms" for a mixed crypto-bearing SBOM.
    artifact_item_type: str = "cbom"


def build_latest_cbom_issues(component_id: str) -> CbomIssuesContext:
    from sbomify.apps.plugins.models import AssessmentRun, RegisteredPlugin
    from sbomify.apps.sboms.models import SBOM

    artifact = (
        SBOM.objects.filter(component_id=component_id)
        .filter(models_q_crypto_bearing())
        .order_by("-created_at")
        .values("id", "version", "bom_type")
        .first()
    )
    if not artifact:
        return CbomIssuesContext()
    item_type = "cbom" if artifact["bom_type"] == SBOM.BomType.CBOM else "sboms"

    results = list(
        AssessmentRun.objects.filter(sbom_id=artifact["id"], category="compliance", status="completed")
        .order_by("plugin_name", "-created_at")
        .distinct("plugin_name")
        .values_list("plugin_name", "result")
    )
    if not results:
        return CbomIssuesContext(
            artifact_version=artifact["version"], artifact_id=artifact["id"], artifact_item_type=item_type
        )

    display_names = dict(
        RegisteredPlugin.objects.filter(name__in=[name for name, _ in results]).values_list("name", "display_name")
    )
    issues: list[dict[str, Any]] = []
    for plugin_name, run_result in results:
        for finding in (run_result or {}).get("findings", []):
            if finding.get("status") not in ("fail", "warning"):
                continue
            issues.append(
                {
                    "status": finding["status"],
                    "severity": finding.get("severity") or "info",
                    "title": finding.get("title") or "Untitled finding",
                    "description": finding.get("description") or "",
                    "check": display_names.get(plugin_name, plugin_name),
                }
            )
    issues.sort(key=lambda row: (0 if row["status"] == "fail" else 1, SEVERITY_RANK.get(row["severity"], 5)))
    return CbomIssuesContext(
        issues=issues,
        terms=[f"{row['title']} {row['check']}".lower() for row in issues],
        severities=[row["severity"] for row in issues],
        artifact_version=artifact["version"],
        artifact_id=artifact["id"],
        artifact_item_type=item_type,
    )


def models_q_crypto_bearing() -> Any:
    """Q filter for artifacts whose crypto findings belong on the component page."""
    from django.db.models import Q

    from sbomify.apps.sboms.models import SBOM

    return Q(bom_type=SBOM.BomType.CBOM) | Q(bom_type=SBOM.BomType.SBOM, has_crypto_assets=True)


@dataclass(frozen=True)
class ComponentVulnerabilitiesContext:
    """The component page's vulnerabilities panel, as one request sees it.

    ``summary`` counts every finding of the newest SBOM; ``panel`` holds only the
    page of rows being rendered. Keeping them apart is the point: the header
    badge has to stay true whatever the reader has filtered the table down to,
    and computing it from the page would make it read "5 findings" on a
    component with two thousand.
    """

    summary: dict[str, Any] | None = None
    panel: dict[str, Any] | None = None
    sbom_id: str | None = None
    version: str | None = None

    @property
    def has_findings(self) -> bool:
        return bool(self.panel and self.panel["unfiltered_total"])


def build_component_vulnerabilities(component_id: str, query: FindingQuery) -> ComponentVulnerabilitiesContext:
    """The newest SBOM's findings, summarised whole and paged for display.

    Rows are derived on every request rather than cached. The derivation is the
    cheap half — 0.49 s against the 5.10 s of rendering them all, and most of
    that 0.49 s was the VEX fetch, which :func:`load_vex_suppressions` now caches
    across requests. What made the page time out was handing the template 2,390
    rows to show five of, and that is what paging removes.
    """
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.kev import kev_ids_for_serialization
    from sbomify.apps.vulnerability_scanning.services.finding_browse import browse_finding_rows
    from sbomify.apps.vulnerability_scanning.utils import (
        extract_finding_rows,
        extract_severity_counts,
        merge_findings_by_alias,
    )
    from sbomify.apps.vulnerability_scanning.vex import load_vex_suppressions

    latest_sbom = (
        SBOM.objects.filter(component_id=component_id, bom_type=SBOM.BomType.SBOM)
        .order_by("-created_at")
        .values("id", "version")
        .first()
    )
    if not latest_sbom:
        return ComponentVulnerabilitiesContext()

    sbom_id = latest_sbom["id"]
    # One query, ordered so the newest run of each provider comes first, and the
    # blob is only pulled for those. The first row also answers "did anything
    # scan this at all", which is what the summary fallback needs.
    provider_results = list(
        AssessmentRun.objects.filter(sbom_id=sbom_id, category="security", status="completed")
        .order_by("plugin_name", "-created_at")
        .distinct("plugin_name")
        .values_list("result", flat=True)
    )
    if not provider_results:
        return ComponentVulnerabilitiesContext(sbom_id=sbom_id, version=latest_sbom["version"])

    rows = extract_finding_rows(
        merge_findings_by_alias(provider_results),
        vex_statements=load_vex_suppressions(component_id),
        kev_ids=kev_ids_for_serialization(),
    )

    # The header badge counts the same merged view the table shows, minus what
    # VEX suppressed, matching the Trust Center posture, which lists suppressed
    # findings separately rather than inside the severity counts.
    summary: dict[str, Any] | None = None
    if rows:
        open_rows = [row for row in rows if not row["vex_suppressed"]]
        summary = {
            "total": len(open_rows),
            "critical": sum(1 for row in open_rows if row["severity"] == "critical"),
            "high": sum(1 for row in open_rows if row["severity"] == "high"),
            "medium": sum(1 for row in open_rows if row["severity"] == "medium"),
            "low": sum(1 for row in open_rows if row["severity"] == "low"),
            "suppressed": len(rows) - len(open_rows),
        }
    else:
        # A result can carry a summary but no findings list (summary-only
        # providers, legacy blobs), and the badge reads it rather than showing
        # "clean" for a scan that did find things.
        summary = max(
            (extract_severity_counts(result) for result in provider_results),
            key=lambda counts: counts["total"],
        )

    return ComponentVulnerabilitiesContext(
        summary=summary,
        panel=browse_finding_rows(rows, query),
        sbom_id=sbom_id,
        version=latest_sbom["version"],
    )
