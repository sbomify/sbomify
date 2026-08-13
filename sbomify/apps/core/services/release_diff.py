"""What changed between two releases of a product.

Derived on read from the stored artifacts, never persisted: component
adds/removes/bumps from the pinned SBOMs' package lists, and the
vulnerability delta from the stored scan results — alias-merged and
VEX-resolved with the same helpers the dashboards use, so "introduced"
and "resolved" mean exactly what the release pages show.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sbomify.apps.core.services import csv_exports
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import SBOM

if TYPE_CHECKING:
    from sbomify.apps.core.models import Release
    from sbomify.apps.teams.models import Team


def _release_sboms(release: Release) -> list[SBOM]:
    return [
        artifact.sbom
        for artifact in release.artifacts.select_related("sbom__component").all()
        if artifact.sbom is not None and artifact.sbom.bom_type == SBOM.BomType.SBOM.value
    ]


def sibling_releases_for(team_id: Any, product_id: str, *, exclude_release_id: str) -> list[Release]:
    """The product's other releases, newest first — the baseline selector's
    option list, kept here so views hold no release queries of their own."""
    from sbomify.apps.core.models import Release

    return list(
        Release.objects.filter(product_id=product_id, product__team_id=team_id)
        .exclude(id=exclude_release_id)
        .order_by("-created_at")
    )


def _package_versions(release: Release) -> tuple[dict[str, set[str]], list[str]]:
    """(package name → versions the release ships, unreadable artifact names).

    An unreadable pinned SBOM must be reported, not skipped: its absence
    silently deletes every one of its packages from the delta, and a diff
    presenting "no changes" over a hole is worse than an error.
    """
    versions: dict[str, set[str]] = defaultdict(set)
    unreadable: list[str] = []
    for sbom in _release_sboms(release):
        payload = csv_exports._load_payload(sbom)
        if payload is None:
            unreadable.append(f"{sbom.component.name} ({sbom.name} {sbom.version or ''})".strip())
            continue
        for package in csv_exports._packages(payload, sbom.format):
            if package["name"]:
                versions[package["name"]].add(package["version"] or "")
    return versions, sorted(unreadable)


def _live_findings(team: Team, release: Release) -> dict[str, dict[str, Any]]:
    """Alias-merged live findings for the release, keyed by advisory id.

    VEX-suppressed findings are excluded on both sides, so a finding the
    customer dispositioned between two releases reads as resolved — which is
    what the posture actually did.
    """
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunStatus
    from sbomify.apps.vulnerability_scanning.utils import (
        extract_finding_rows,
        is_vulnerability,
        merge_findings_by_alias,
    )
    from sbomify.apps.vulnerability_scanning.vex import load_vex_suppressions

    sboms = _release_sboms(release)
    runs = (
        AssessmentRun.objects.filter(
            sbom_id__in=[sbom.id for sbom in sboms],
            sbom__component__team=team,
            category=AssessmentCategory.SECURITY.value,
            status=RunStatus.COMPLETED.value,
        )
        .select_related("sbom")
        .order_by("sbom_id", "plugin_name", "-created_at", "-id")
        .distinct("sbom_id", "plugin_name")
    )

    by_sbom: dict[str, list[Any]] = defaultdict(list)
    for run in runs:
        by_sbom[run.sbom_id].append(run)

    vex_cache: dict[Any, list[dict[str, Any]]] = {}
    findings: dict[str, dict[str, Any]] = {}
    for sbom_id, sbom_runs in by_sbom.items():
        merged = merge_findings_by_alias([run.result for run in sbom_runs])
        merged["findings"] = [
            finding
            for finding in merged.get("findings") or []
            if isinstance(finding, dict) and is_vulnerability(finding)
        ]
        statements = load_vex_suppressions(sbom_runs[0].sbom.component_id, cache=vex_cache)
        for row in extract_finding_rows(merged, statements):
            if row.get("vex_suppressed"):
                continue
            finding_id = row.get("id") or ""
            if finding_id and finding_id not in findings:
                findings[finding_id] = {
                    "id": finding_id,
                    "severity": row.get("severity") or "",
                    "package": row.get("package") or "",
                    "version": row.get("version") or "",
                }
    return findings


def _release_summary(release: Release) -> dict[str, Any]:
    return {
        "id": release.id,
        "name": release.name,
        "version": release.version,
        "product_id": release.product_id,
    }


def diff_releases(team: Team, from_release: Release, to_release: Release) -> ServiceResult[dict[str, Any]]:
    """The delta from ``from_release`` to ``to_release`` of one product."""
    if from_release.product.team_id != team.id or to_release.product.team_id != team.id:
        return ServiceResult.failure("Release not found", status_code=404)
    if from_release.product_id != to_release.product_id:
        return ServiceResult.failure(
            "Releases belong to different products; a diff compares two releases of one product.",
            status_code=400,
        )

    old_packages, old_unreadable = _package_versions(from_release)
    new_packages, new_unreadable = _package_versions(to_release)

    added = [
        {"name": name, "version": "; ".join(sorted(new_packages[name]))}
        for name in sorted(set(new_packages) - set(old_packages), key=str.lower)
    ]
    removed = [
        {"name": name, "version": "; ".join(sorted(old_packages[name]))}
        for name in sorted(set(old_packages) - set(new_packages), key=str.lower)
    ]
    changed = [
        {
            "name": name,
            "from_version": "; ".join(sorted(old_packages[name])),
            "to_version": "; ".join(sorted(new_packages[name])),
        }
        for name in sorted(set(old_packages) & set(new_packages), key=str.lower)
        if old_packages[name] != new_packages[name]
    ]

    old_findings = _live_findings(team, from_release)
    new_findings = _live_findings(team, to_release)
    introduced = [new_findings[fid] for fid in sorted(set(new_findings) - set(old_findings))]
    resolved = [old_findings[fid] for fid in sorted(set(old_findings) - set(new_findings))]

    return ServiceResult.success(
        {
            "from_release": _release_summary(from_release),
            "to_release": _release_summary(to_release),
            "components": {"added": added, "removed": removed, "changed": changed},
            "vulnerabilities": {"introduced": introduced, "resolved": resolved},
            "unreadable_artifacts": sorted(set(old_unreadable) | set(new_unreadable)),
            "counts": {
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
                "introduced": len(introduced),
                "resolved": len(resolved),
            },
        }
    )


def build_diff_page_context(
    team: Team, product_id: str, release_id: str, other_release_id: str
) -> ServiceResult[dict[str, Any]]:
    """Everything the diff page renders: the two releases, the delta, and the
    product's sibling releases for the baseline selector."""
    from sbomify.apps.core.models import Release

    releases = Release.objects.filter(product_id=product_id, product__team=team).select_related("product")
    to_release = next((release for release in releases if release.id == release_id), None)
    from_release = next((release for release in releases if release.id == other_release_id), None)
    if to_release is None or from_release is None:
        return ServiceResult.failure("Release not found", status_code=404)

    result = diff_releases(team, from_release, to_release)
    if not result.ok:
        return result

    siblings = sorted(
        (release for release in releases if release.id != release_id),
        key=lambda release: release.created_at or 0,
        reverse=True,
    )
    return ServiceResult.success(
        {
            "diff": result.value,
            "to_release": to_release,
            "from_release": from_release,
            "product": to_release.product,
            "sibling_releases": siblings,
        }
    )
