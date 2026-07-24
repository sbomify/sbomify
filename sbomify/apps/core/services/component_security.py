"""Component-page crypto issue rows.

The drill-down table on the private component page shows the fail/warning
findings of the component's newest crypto-bearing artifact: the newest CBOM
when one exists, else the newest mixed SBOM stamped ``has_crypto_assets=True``
(mixed documents keep ``bom_type=sbom`` so they retain NTIA and vulnerability
assessment, but their crypto findings must still surface here).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
