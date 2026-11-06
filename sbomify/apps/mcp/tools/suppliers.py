"""Workspace supplier tools.

A supplier is a vendor the workspace collects artifacts from: a name and who to
contact there. Keeping the list current is the bookkeeping CRA supply-chain due
diligence asks for, and the kind an agent can do from a contract or an email.

The tools call the REST views, which confine every supplier to the workspace.
Removing a supplier is not exposed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from .. import serializers
from ..auth import Principal
from ..limits import untrusted
from ._base import clamp_page, mcp_tool, not_found, resolve_workspace, run_db, unwrap_view, workspace_key

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _supplier(row: dict[str, Any]) -> dict[str, Any]:
    return serializers.compact(
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "contact_name": row.get("contact_name"),
            "contact_email": row.get("contact_email"),
            "website": row.get("website"),
            # Notes have no length limit, and one long enough would make every
            # page holding the supplier fail the response cap.
            "notes": untrusted(row.get("notes")),
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        }
    )


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "list_suppliers", "workspace:read")
    async def list_suppliers(
        principal: Principal, search: str | None = None, page: int = 1, page_size: int = 25
    ) -> dict[str, Any]:
        """List the vendors this workspace collects artifacts from, by name.

        `search` matches the supplier name or contact email. Check this before
        `create_supplier`, since names are unique in a workspace.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.teams import apis

            team = resolve_workspace(principal)
            rows = unwrap_view(
                apis.list_workspace_suppliers(principal.request, workspace_key(team), search=(search or "").strip()),
                action="Listing suppliers",
            )["result"]
            rows = sorted(rows, key=lambda row: (row["name"].lower(), row["id"]))
            safe_page, safe_size = clamp_page(page, page_size)
            start = (safe_page - 1) * safe_size
            return serializers.paginated(
                [_supplier(row) for row in rows[start : start + safe_size]],
                page=safe_page,
                page_size=safe_size,
                total=len(rows),
            )

        return await run_db(call)

    @mcp_tool(mcp, "create_supplier", "workspace:manage", writes=True, idempotent=False)
    async def create_supplier(
        principal: Principal,
        name: str,
        contact_name: str = "",
        contact_email: str = "",
        website: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Add a vendor to the workspace's supplier list.

        `name` must be unique in the workspace. The contact fields can be left
        blank and filled in later with `update_supplier`.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.teams import apis
            from sbomify.apps.teams.schemas import SupplierCreateSchema

            team = resolve_workspace(principal)
            try:
                payload = SupplierCreateSchema(
                    name=name, contact_name=contact_name, contact_email=contact_email, website=website, notes=notes
                )
            except ValidationError as exc:
                raise ToolError(f"Invalid supplier: {exc}") from exc
            created = unwrap_view(
                apis.create_workspace_supplier(principal.request, workspace_key(team), payload),
                action="Supplier creation",
            )
            return _supplier(created)

        return await run_db(call)

    @mcp_tool(mcp, "update_supplier", "workspace:manage", writes=True, idempotent=True)
    async def update_supplier(
        principal: Principal,
        supplier_id: str,
        name: str | None = None,
        contact_name: str | None = None,
        contact_email: str | None = None,
        website: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Change a supplier's details. Only the fields you pass change."""

        def call() -> dict[str, Any]:
            from sbomify.apps.teams import apis
            from sbomify.apps.teams.models import Supplier
            from sbomify.apps.teams.schemas import SupplierUpdateSchema

            team = resolve_workspace(principal)
            if not Supplier.objects.filter(pk=supplier_id, team=team).exists():
                raise not_found("supplier", supplier_id)
            fields = {
                key: value
                for key, value in {
                    "name": name,
                    "contact_name": contact_name,
                    "contact_email": contact_email,
                    "website": website,
                    "notes": notes,
                }.items()
                if value is not None
            }
            if not fields:
                raise ToolError("Nothing to update: pass at least one field.")
            try:
                payload = SupplierUpdateSchema(**fields)
            except ValidationError as exc:
                raise ToolError(f"Invalid supplier: {exc}") from exc
            updated = unwrap_view(
                apis.update_workspace_supplier(principal.request, workspace_key(team), supplier_id, payload),
                action="Supplier update",
            )
            return _supplier(updated)

        return await run_db(call)
