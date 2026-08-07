"""Component-page crypto and hardware issue rows.

The drill-down tables on the private component page show the fail/warning
findings of the component's newest crypto-bearing artifact: the newest CBOM
when one exists, else the newest mixed SBOM stamped ``has_crypto_assets=True``
(mixed documents keep ``bom_type=sbom`` so they retain NTIA and vulnerability
assessment, but their crypto findings must still surface here). The hardware
table is the same drill-down over the newest hardware-bearing artifact.
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


@dataclass(frozen=True)
class HbomIssuesContext:
    issues: list[dict[str, Any]] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    severities: list[str] = field(default_factory=list)
    artifact_version: str | None = None
    artifact_id: str | None = None


# The only plugin that scores hardware. Its findings are the card's whole
# content: an NTIA or BSI run on a mixed hardware-bearing SBOM says nothing
# about the parts list, and those runs already have the assessments column.
_HARDWARE_PLUGIN = "hbom-structure"


def build_latest_hbom_issues(component_id: str) -> HbomIssuesContext:
    """Hardware findings of the component's newest hardware-bearing artifact.

    An HBOM outranks a newer hardware-bearing SBOM, as on the component
    hardware page — the two must describe the same artifact, and picking
    strictly by date would empty this card the moment a software SBOM is
    uploaded. Only ``hbom``-tagged artifacts carry hardware findings today, so
    the mixed-SBOM fallback yields no rows and the card stays off the page.
    """
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM

    artifacts = (
        SBOM.objects.filter(component_id=component_id)
        .filter(models_q_hardware_bearing())
        .order_by("-created_at")
        .values("id", "version")
    )
    artifact = artifacts.filter(bom_type=SBOM.BomType.HBOM).first() or artifacts.first()
    if not artifact:
        return HbomIssuesContext()

    run_result = (
        AssessmentRun.objects.filter(sbom_id=artifact["id"], plugin_name=_HARDWARE_PLUGIN, status="completed")
        .order_by("-created_at")
        .values_list("result", flat=True)
        .first()
    )
    issues = [
        {
            "status": finding["status"],
            "severity": finding.get("severity") or "info",
            "title": finding.get("title") or "Untitled finding",
            "description": finding.get("description") or "",
            "remediation": finding.get("remediation") or "",
        }
        for finding in (run_result or {}).get("findings") or []
        if finding.get("status") in ("fail", "warning")
    ]
    issues.sort(key=lambda row: (0 if row["status"] == "fail" else 1, SEVERITY_RANK.get(row["severity"], 5)))
    return HbomIssuesContext(
        issues=issues,
        # Every field this plugin scores is named in the title or the citation
        # below it, so the search box has to reach both.
        terms=[f"{row['title']} {row['description']}".lower() for row in issues],
        severities=[row["severity"] for row in issues],
        artifact_version=artifact["version"],
        artifact_id=artifact["id"],
    )


def models_q_crypto_bearing() -> Any:
    """Q filter for artifacts whose crypto findings belong on the component page."""
    from django.db.models import Q

    from sbomify.apps.sboms.models import SBOM

    return Q(bom_type=SBOM.BomType.CBOM) | Q(bom_type=SBOM.BomType.SBOM, has_crypto_assets=True)


def models_q_hardware_bearing() -> Any:
    """Q filter for artifacts whose hardware parts belong on the component page.

    The crypto counterpart's shape: a dedicated HBOM, or a mixed SBOM stamped
    ``has_hardware_components`` at upload (mixed documents keep
    ``bom_type=sbom`` so they retain NTIA and vulnerability assessment, but
    their device components must still surface).

    An ``hbom`` row qualifies on its bom_type alone, whatever the stamp says —
    the same escape hatch the plugin dispatch gate uses. The stamp is ``None``
    on every row predating the field, and the field's contract reads ``None`` as
    unknown rather than false, so requiring ``True`` of an HBOM would hide a
    hardware artifact until the retag backfill has run. The stamp is load-bearing
    only for a ``sbom`` row, where it is the sole signal separating a mixed
    hardware document from the software-only majority: those stay out unknown,
    since reading every pre-field SBOM from storage to find the few with devices
    is what the stamp exists to avoid.
    """
    from django.db.models import Q

    from sbomify.apps.sboms.models import SBOM

    return Q(bom_type=SBOM.BomType.HBOM) | Q(bom_type=SBOM.BomType.SBOM, has_hardware_components=True)
