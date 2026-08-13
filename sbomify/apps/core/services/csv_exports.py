"""Auditor-facing CSV exports: inventory, licences, findings, vulnerabilities.

Procurement and auditors ask for tabular data; before this the answer was
scripting against the API. Four generators, one shape: a ``ServiceResult[str]``
of CSV text the endpoint serves as an attachment.

Two rules every generator follows:

* **The writer is defusedcsv.** Every cell that matters — package names,
  licence ids, vulnerability titles — originates in uploaded artifacts or
  scanner output, and a value like ``=cmd|...`` must open in a spreadsheet as
  text, not as a formula.
* **Unreadable artifacts surface as explicit rows.** A parts list that
  silently omits the SBOMs it could not read looks complete while it is not,
  which for an auditor is worse than an error.
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from botocore.exceptions import BotoCoreError, ClientError
from defusedcsv import csv

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import SBOMDataError, get_sbom_data_bytes

if TYPE_CHECKING:
    from sbomify.apps.core.models import Component, Product, Release
    from sbomify.apps.teams.models import Team

MAX_PARSE_BYTES = 50 * 1024 * 1024
"""Largest stored artifact an export will pull into memory; larger ones get
the explicit unreadable row instead of an OOM."""

UNREADABLE = "(unreadable artifact)"


def _latest_sboms(team: Team, product: Product | None = None) -> list[SBOM]:
    """The newest ``bom_type=sbom`` per component in scope — the dashboards'
    counting rule, so an export never stacks superseded uploads."""
    queryset = SBOM.objects.filter(component__team=team, bom_type=SBOM.BomType.SBOM)
    if product is not None:
        queryset = queryset.filter(component__products=product)
    return list(
        queryset.select_related("component").order_by("component_id", "-created_at", "-id").distinct("component_id")
    )


def _load_payload(sbom: SBOM) -> dict[str, Any] | None:
    """The parsed document, or ``None`` for anything unreadable."""
    try:
        _, raw = get_sbom_data_bytes(sbom.id)
    except (SBOMDataError, ClientError, BotoCoreError):
        # get_sbom_data_bytes normalises most failures into SBOMDataError, but
        # the S3 fetch itself re-raises botocore errors; anything else is a
        # programming error that must surface, not an unreadable artifact.
        return None
    if raw is None or len(raw) > MAX_PARSE_BYTES:
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cyclonedx_licenses(entry: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for lic in entry.get("licenses") or []:
        if not isinstance(lic, dict):
            continue
        nested = lic.get("license")
        if isinstance(nested, dict):
            label = nested.get("id") or nested.get("name")
        elif isinstance(nested, str):
            label = nested
        else:
            label = lic.get("expression")
        if isinstance(label, str) and label:
            labels.append(label)
    return labels


def _spdx_supplier(value: Any) -> str:
    """``Organization: npm`` / ``Person: Jane`` → the bare name."""
    if not isinstance(value, str):
        return ""
    _, _, name = value.partition(":")
    return (name or value).strip()


def _packages(payload: dict[str, Any], sbom_format: str) -> list[dict[str, Any]]:
    """Normalise CycloneDX components / SPDX packages into one row shape."""
    rows: list[dict[str, Any]] = []
    if sbom_format.lower() == "cyclonedx":
        for entry in payload.get("components") or []:
            if not isinstance(entry, dict):
                continue
            supplier = entry.get("supplier")
            rows.append(
                {
                    "name": entry.get("name") or "",
                    "version": entry.get("version") or "",
                    "supplier": (supplier or {}).get("name", "") if isinstance(supplier, dict) else "",
                    "licenses": _cyclonedx_licenses(entry),
                    "purl": entry.get("purl") or "",
                }
            )
    else:
        for entry in payload.get("packages") or []:
            if not isinstance(entry, dict):
                continue
            declared = entry.get("licenseDeclared")
            if not isinstance(declared, str) or not declared or declared == "NOASSERTION":
                declared = entry.get("licenseConcluded")
            purl = ""
            for ref in entry.get("externalRefs") or []:
                if isinstance(ref, dict) and ref.get("referenceType") == "purl":
                    purl = ref.get("referenceLocator") or ""
                    break
            rows.append(
                {
                    "name": entry.get("name") or "",
                    "version": entry.get("versionInfo") or "",
                    "supplier": _spdx_supplier(entry.get("supplier")),
                    "licenses": (
                        [declared] if isinstance(declared, str) and declared and declared != "NOASSERTION" else []
                    ),
                    "purl": purl,
                }
            )
    return rows


def _csv(header: list[str], rows: list[list[Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)  # type: ignore[no-untyped-call]
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue()


def export_inventory_csv(team: Team, product: Product | None = None) -> ServiceResult[str]:
    """Package inventory across the newest SBOM per component."""
    rows: list[list[Any]] = []
    for sbom in _latest_sboms(team, product):
        payload = _load_payload(sbom)
        if payload is None:
            rows.append([sbom.component.name, sbom.version or "", UNREADABLE, "", "", "", ""])
            continue
        for package in _packages(payload, sbom.format):
            rows.append(
                [
                    sbom.component.name,
                    sbom.version or "",
                    package["name"],
                    package["version"],
                    package["supplier"],
                    "; ".join(package["licenses"]),
                    package["purl"],
                ]
            )
    return ServiceResult.success(
        _csv(["Component", "SBOM Version", "Package", "Version", "Supplier", "Licenses", "PURL"], rows)
    )


def export_licenses_csv(
    team: Team,
    product: Product | None = None,
    release: Release | None = None,
) -> ServiceResult[str]:
    """Distinct licences in scope, with how many packages and components carry each."""
    if release is not None:
        sboms = [
            artifact.sbom
            for artifact in release.artifacts.select_related("sbom__component").all()
            if artifact.sbom is not None and artifact.sbom.bom_type == SBOM.BomType.SBOM.value
        ]
    else:
        sboms = _latest_sboms(team, product)

    packages_by_license: dict[str, set[tuple[str, str]]] = defaultdict(set)
    components_by_license: dict[str, set[str]] = defaultdict(set)
    for sbom in sboms:
        payload = _load_payload(sbom)
        if payload is None:
            continue
        for package in _packages(payload, sbom.format):
            for label in package["licenses"]:
                packages_by_license[label].add((package["name"], package["version"]))
                components_by_license[label].add(sbom.component_id)

    rows = [
        [label, len(packages_by_license[label]), len(components_by_license[label])]
        for label in sorted(packages_by_license)
    ]
    return ServiceResult.success(_csv(["License", "Packages", "Components"], rows))


def export_findings_csv(sbom: SBOM) -> ServiceResult[str]:
    """Latest compliance-style findings per plugin for one SBOM."""
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunStatus

    runs = (
        AssessmentRun.objects.filter(sbom=sbom, status=RunStatus.COMPLETED.value)
        .exclude(category=AssessmentCategory.SECURITY.value)
        .order_by("plugin_name", "-created_at", "-id")
        .distinct("plugin_name")
    )
    rows: list[list[Any]] = []
    for run in runs:
        result = run.result if isinstance(run.result, dict) else {}
        for finding in result.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            rows.append(
                [
                    run.plugin_name,
                    finding.get("id") or "",
                    finding.get("title") or "",
                    finding.get("status") or "",
                    finding.get("description") or finding.get("details") or "",
                ]
            )
    return ServiceResult.success(_csv(["Plugin", "Check", "Title", "Status", "Description"], rows))


def export_vulnerabilities_csv(
    team: Team,
    component: Component | None = None,
    release: Release | None = None,
) -> ServiceResult[str]:
    """Vulnerability findings with the post-VEX analysis state, like the dashboards.

    Same helpers the UI uses — alias-merged across providers, bookkeeping rows
    dropped, VEX statements resolved live — so the export never disagrees with
    the page beside it.
    """
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunStatus
    from sbomify.apps.vulnerability_scanning.utils import (
        extract_finding_rows,
        is_vulnerability,
        merge_findings_by_alias,
    )
    from sbomify.apps.vulnerability_scanning.vex import load_vex_suppressions

    if release is not None:
        sbom_ids = [
            artifact.sbom_id
            for artifact in release.artifacts.select_related("sbom").all()
            if artifact.sbom is not None and artifact.sbom.bom_type == SBOM.BomType.SBOM.value
        ]
        runs = AssessmentRun.objects.filter(sbom_id__in=sbom_ids)
    elif component is not None:
        runs = AssessmentRun.objects.filter(sbom__component=component)
    else:
        latest_ids = [sbom.id for sbom in _latest_sboms(team)]
        runs = AssessmentRun.objects.filter(sbom_id__in=latest_ids)

    runs = (
        runs.filter(sbom__component__team=team, category=AssessmentCategory.SECURITY.value)
        .filter(status=RunStatus.COMPLETED.value)
        .select_related("sbom", "sbom__component")
        .order_by("sbom_id", "plugin_name", "-created_at", "-id")
        .distinct("sbom_id", "plugin_name")
    )

    by_sbom: dict[str, list[AssessmentRun]] = defaultdict(list)
    for run in runs:
        by_sbom[run.sbom_id].append(run)

    vex_cache: dict[Any, list[dict[str, Any]]] = {}
    rows: list[list[Any]] = []
    for sbom_id, sbom_runs in by_sbom.items():
        merged = merge_findings_by_alias([run.result for run in sbom_runs])
        merged["findings"] = [
            finding
            for finding in merged.get("findings") or []
            if isinstance(finding, dict) and is_vulnerability(finding)
        ]
        sbom = sbom_runs[0].sbom
        providers = "; ".join(sorted({run.plugin_name for run in sbom_runs}))
        statements = load_vex_suppressions(sbom.component_id, cache=vex_cache)
        for row in extract_finding_rows(merged, statements):
            rows.append(
                [
                    row.get("id") or "",
                    row.get("severity") or "",
                    row.get("cvss_score") if row.get("cvss_score") is not None else "",
                    row.get("package") or "",
                    row.get("version") or "",
                    sbom.component.name,
                    row.get("vex_state") or "",
                    "yes" if row.get("vex_suppressed") else "",
                    providers,
                ]
            )
    return ServiceResult.success(
        _csv(
            [
                "Vulnerability",
                "Severity",
                "CVSS",
                "Package",
                "Version",
                "Component",
                "Analysis State",
                "Suppressed",
                "Providers",
            ],
            rows,
        )
    )
