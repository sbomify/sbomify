"""Security controls tools: catalogs, controls and their statuses, evidence and mappings.

Read only. Every controls write (activating or importing a catalog, setting a
status, adding evidence, mapping controls) is held to workspace owners and
admins, the administrative tier no MCP tool may reach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal
from ._base import DETAIL_COLLECTION_LIMIT, clamp_page, mcp_tool, not_found, resolve_workspace, run_db, unwrap_view
from .catalog import _lookup_product

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _dumped(result: tuple[int, Any], *, action: str) -> list[dict[str, Any]]:
    """A controls view's list of schemas as JSON rows, or its refusal as a ``ToolError``."""
    status, payload = result
    if status >= 400:
        unwrap_view(result, action=action)
    return [row.model_dump(mode="json") for row in payload]


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "list_control_catalogs", "workspace:read")
    async def list_control_catalogs(principal: Principal, include_inactive: bool = False) -> dict[str, Any]:
        """List the workspace's security control catalogs, such as the CRA or ISO 27001 requirements.

        Inactive catalogs are left out unless `include_inactive` is true. Read a
        catalog's controls with `list_controls`.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.controls import apis

            resolve_workspace(principal)
            rows = _dumped(apis.list_catalogs(principal.request, include_inactive), action="Listing catalogs")
            return {"catalogs": rows}

        return await run_db(query)

    @mcp_tool(mcp, "list_controls", "workspace:read")
    async def list_controls(
        principal: Principal,
        catalog_id: str,
        product_id: str | None = None,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List a catalog's controls with their implementation status.

        Statuses are the workspace-wide ones unless `product_id` names a product.
        `status` keeps only controls in that state (compliant, partial,
        not_implemented or not_applicable). `search` matches the control id,
        group and title. Read one control's evidence with `get_control`.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.controls import apis
            from sbomify.apps.controls.models import ControlCatalog, ControlStatus

            team = resolve_workspace(principal)
            if not ControlCatalog.objects.filter(pk=catalog_id, team=team).exists():
                raise not_found("control catalog", catalog_id)
            if product_id is not None:
                _lookup_product(principal, product_id)
            if status is not None and status not in ControlStatus.Status.values:
                raise ToolError(f"Unknown status {status!r}; expected one of {', '.join(ControlStatus.Status.values)}.")

            rows = _dumped(apis.list_controls(principal.request, catalog_id, product_id), action="Listing controls")
            term = (search or "").strip().lower()
            matched = [
                row
                for row in rows
                if (status is None or row["status"] == status)
                and (not term or any(term in row[field].lower() for field in ("control_id", "group", "title")))
            ]
            safe_page, safe_size = clamp_page(page, page_size)
            start = (safe_page - 1) * safe_size
            return serializers.paginated(
                [
                    serializers.compact(
                        {key: row[key] for key in ("id", "control_id", "group", "title", "status", "notes")}
                    )
                    for row in matched[start : start + safe_size]
                ],
                page=safe_page,
                page_size=safe_size,
                total=len(matched),
            )

        return await run_db(query)

    @mcp_tool(mcp, "get_control", "workspace:read")
    async def get_control(principal: Principal, control_id: str) -> dict[str, Any]:
        """One control in full: its description, workspace-wide status, evidence, and mappings to other catalogs.

        `control_id` is the `id` from `list_controls`. Product statuses come
        from `list_controls` with a `product_id`.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.controls import apis
            from sbomify.apps.controls.models import Control, ControlEvidence, ControlStatus

            team = resolve_workspace(principal)
            control = Control.objects.select_related("catalog").filter(pk=control_id, catalog__team=team).first()
            if control is None:
                raise not_found("control", control_id)

            mappings = _dumped(apis.list_control_mappings(principal.request, control_id), action="Reading mappings")
            # Read directly rather than through the evidence view, which creates
            # a status row for a control that has none: a read must not write.
            current = ControlStatus.objects.filter(control=control, product__isnull=True).first()
            evidence = ControlEvidence.objects.filter(control_status=current).order_by("-created_at", "id")
            evidence_total = evidence.count() if current else 0
            return serializers.compact(
                {
                    "id": control.id,
                    "control_id": control.control_id,
                    "group": control.group,
                    "title": control.title,
                    "description": control.description,
                    "catalog": {"id": control.catalog.id, "name": control.catalog.name},
                    "status": current.status if current else ControlStatus.Status.NOT_IMPLEMENTED.value,
                    "notes": current.notes if current else "",
                    "evidence": serializers.capped(
                        [
                            serializers.compact(
                                {
                                    "id": ev.id,
                                    "evidence_type": ev.evidence_type,
                                    "title": ev.title,
                                    "url": ev.url,
                                    "document_id": ev.document_id,
                                    "description": ev.description,
                                }
                            )
                            for ev in (evidence[:DETAIL_COLLECTION_LIMIT] if current else [])
                        ],
                        total=evidence_total,
                        limit=DETAIL_COLLECTION_LIMIT,
                    )
                    if evidence_total
                    else None,
                    "mappings": serializers.capped(
                        [
                            serializers.compact({key: row[key] for key in row if key not in ("id", "created_at")})
                            for row in mappings[:DETAIL_COLLECTION_LIMIT]
                        ],
                        total=len(mappings),
                        limit=DETAIL_COLLECTION_LIMIT,
                    )
                    if mappings
                    else None,
                }
            )

        return await run_db(query)
