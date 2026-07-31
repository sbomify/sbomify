from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.forms import SbomDeleteForm
from sbomify.apps.sboms.services.sboms_table import delete_sbom_from_request

# Human labels for the artifact's stored ``source`` and ``format``. Anything
# unmapped falls back to a title-cased version of the raw value.
_SOURCE_LABELS = {
    "manual_upload": "Manual upload",
    "api": "API",
    "dependency-track": "Dependency-Track",
}
_FORMAT_LABELS = {
    "cyclonedx": "CycloneDX",
    "openvex": "OpenVEX",
    "csaf": "CSAF",
}


def _format_label(fmt: str | None, version: str | None) -> str:
    base = _FORMAT_LABELS.get((fmt or "").lower(), (fmt or "VEX").title())
    # OpenVEX/CSAF versions are noisy ("v0.2.0"); only CycloneDX's short version reads well inline.
    return f"{base} {version}" if version and (fmt or "").lower() == "cyclonedx" else base


def _source_label(source: str | None) -> str:
    return _SOURCE_LABELS.get(source or "", (source or "Unknown").replace("_", " ").title())


def build_component_vex_context(request: HttpRequest, component_id: str) -> ServiceResult[dict[str, Any]]:
    """Context for the component's VEX Documents card.

    Lists the VEX documents uploaded for the component (via the file uploader or
    the API). The sbomify-triage overlay is deliberately excluded — it is not an
    uploaded document but the in-app triage decisions, managed from the per-finding
    Triage modal.
    """
    status_code, component = get_component(request, component_id)
    if status_code != 200:
        return ServiceResult.failure(component.get("detail", "Unknown error"))

    # get_component returns 200 for PUBLIC and GATED components to any caller (it
    # is the public-listing gate). Deriving a VEX's suppressed CVE ids/states from
    # S3 exposes the same content the download path protects, so gate it on
    # component-download access the way the crypto-inventory and download views do.
    from sbomify.apps.core.authz import can
    from sbomify.apps.core.models import Component

    component_obj = Component.objects.filter(pk=component_id).first()
    if component_obj is None or not can(request, "component:access", component_obj):
        return ServiceResult.failure("Forbidden", status_code=403)

    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.vex import (
        TRIAGE_SOURCE,
        _document_from_vex_sbom,
        derive_vex_suppressions,
    )

    rows = (
        SBOM.objects.filter(component_id=component_id, bom_type=SBOM.BomType.VEX)
        .exclude(source=TRIAGE_SOURCE)
        .order_by("-created_at")
    )

    documents: list[dict[str, Any]] = []
    for row in rows:
        # ponytail: one S3 read + derive per VEX to show what it suppresses. A
        # component carries a handful of uploaded VEX, so this is bounded; move
        # the count to a stored column if one ever accumulates many.
        document = _document_from_vex_sbom(row)
        statements = derive_vex_suppressions(document) if document else []
        pairs: dict[str, str | None] = {}
        for statement in statements:
            for vuln_id in statement.get("ids") or []:
                pairs.setdefault(vuln_id.upper(), statement.get("state"))
        cve_summary = [{"id": vuln_id, "state": state} for vuln_id, state in list(pairs.items())[:5]]
        documents.append(
            {
                "id": row.id,
                "name": row.name or row.sbom_filename,
                "format_label": _format_label(row.format, row.format_version),
                "source_label": _source_label(row.source),
                "created_at": row.created_at,
                "statement_count": len(statements),
                "cve_summary": cve_summary,
                "extra_cve_count": max(0, len(pairs) - len(cve_summary)),
                "unreadable": document is None,
            }
        )

    return ServiceResult.success(
        {
            "component_id": component_id,
            "vex_documents": documents,
            "has_crud_permissions": component.get("has_crud_permissions", False),
            "delete_form": SbomDeleteForm(),
        }
    )


def delete_vex_from_request(request: HttpRequest) -> ServiceResult[None]:
    """Delete a VEX document. VEX rows are SBOM records, so this reuses the same
    permission-checked delete path as the SBOMs table."""
    return delete_sbom_from_request(request)
