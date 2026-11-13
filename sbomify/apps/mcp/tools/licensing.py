"""License lookup and validation tools.

The REST endpoints these mirror check no action beyond authentication: the
license list is reference data. ``workspace:read`` is declared so a token
scoped to nothing at all is not offered them, and each still resolves the
caller's workspace, the choke point that refuses a guest like every other tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal
from ._base import clamp_page, mcp_tool, resolve_workspace, run_db

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

MAX_EXPRESSION_LENGTH = 2000


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "search_licenses", "workspace:read")
    async def search_licenses(
        principal: Principal, search: str | None = None, page: int = 1, page_size: int = 25
    ) -> dict[str, Any]:
        """Look up licenses sbomify knows: SPDX identifiers and custom ones.

        `search` matches the identifier or the name, case-insensitively, such
        as "apache" or "GPL-3.0". Use it to find the right SPDX identifier
        before writing a license expression.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.licensing.loader import get_license_list

            resolve_workspace(principal)
            term = (search or "").strip().casefold()
            matches = [
                entry
                for entry in get_license_list()
                if not term or term in entry["key"].casefold() or term in str(entry.get("name", "")).casefold()
            ]
            safe_page, safe_size = clamp_page(page, page_size)
            start = (safe_page - 1) * safe_size
            return serializers.paginated(
                [serializers.compact(entry) for entry in matches[start : start + safe_size]],
                page=safe_page,
                page_size=safe_size,
                total=len(matches),
            )

        return await run_db(query)

    @mcp_tool(mcp, "validate_license_expression", "workspace:read")
    async def validate_license_expression(principal: Principal, expression: str) -> dict[str, Any]:
        """Check a license expression such as "MIT OR Apache-2.0" and normalise it.

        Returns the normalised expression, each license in it and whether
        sbomify knows it, and the ones it does not. `status` is 200 for a valid
        expression and 400 with an `error` otherwise.
        """
        if len(expression) > MAX_EXPRESSION_LENGTH:
            raise ToolError(f"The expression is over {MAX_EXPRESSION_LENGTH} characters.")

        def query() -> dict[str, Any]:
            from sbomify.apps.licensing.loader import validate_expression

            resolve_workspace(principal)
            return serializers.compact(validate_expression(expression))

        return await run_db(query)
