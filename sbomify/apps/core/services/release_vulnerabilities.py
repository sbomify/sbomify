"""The vulnerabilities a release carries, for the internal release page."""

from __future__ import annotations

from typing import Any

from django.db.models import F
from django.http import HttpRequest
from django.urls import reverse

from sbomify.apps.core.authz import can
from sbomify.apps.core.models import Release, ReleaseArtifact
from sbomify.apps.core.services.inventory_page import _counts
from sbomify.apps.core.services.release_lifecycle import untracked_notice
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.services.sboms_table import sbom_vulnerability_counts
from sbomify.apps.vulnerability_scanning.posture import build_release_vuln_postures


def build_release_vulnerabilities(request: HttpRequest, release_id: str) -> ServiceResult[dict[str, Any]]:
    """The release's rollup and each SBOM artifact's own counts.

    The rollup is the one the product page's release table prints, so the
    number a reader clicked through on is the number they land on. The
    per-artifact counts are each SBOM's own report, which is where a reader
    goes next to triage.
    """
    release = Release.objects.select_related("product").filter(pk=release_id).first()
    if release is None:
        return ServiceResult.failure("Release not found", status_code=404)
    if not can(request, "product:read", release.product).allowed:
        return ServiceResult.failure("Access denied", status_code=403)

    posture = build_release_vuln_postures([release])[release.id]

    sbom_ids_by_component: dict[str, list[str]] = {}
    for sbom_id, component_id in ReleaseArtifact.objects.filter(
        release=release,
        sbom__bom_type=SBOM.BomType.SBOM,
        sbom__component__team_id=F("release__product__team_id"),
    ).values_list("sbom_id", "sbom__component_id"):
        sbom_ids_by_component.setdefault(component_id, []).append(sbom_id)

    artifacts: dict[str, dict[str, Any] | None] = {}
    for sbom_id, counts in sbom_vulnerability_counts(sbom_ids_by_component).items():
        artifacts[sbom_id] = None
        if counts is not None:
            artifacts[sbom_id] = counts | {"url": reverse("sboms:sbom_vulnerabilities", args=[sbom_id])}

    findings = posture.get("findings", [])
    for finding in findings:
        state = finding["state"].replace("_", " ").capitalize() or "Suppressed"
        finding["status"] = state if finding["suppressed"] else "Open"

    return ServiceResult.success(
        {
            "assessed": posture.get("has_data", False),
            "counts": _counts(posture.get("counts")),
            "unassessed": posture["unassessed"],
            "suppressed_count": posture.get("suppressed_count", 0),
            "findings": findings,
            "artifacts": artifacts,
            "untracked": untracked_notice(release),
            "last_scanned_at": posture.get("last_scanned_at"),
        }
    )
