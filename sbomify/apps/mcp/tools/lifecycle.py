"""Lifecycle (CLE) and end-of-life readiness tools.

Lifecycle events follow ECMA-428 and are append-only, so they are read here
and recorded by a person in sbomify: an event can never be edited or deleted,
a public product's events are served over TEA, and a product event rewrites the
product's release, end of support and end of life dates.

Events and support definitions hang off four kinds of thing: a product, a
component, a product release and a component release. Each tool takes exactly
one of the four ids and delegates to that scope's REST view, so the checks
those views make are the checks these tools make.

A token is shown a lifecycle tool only when it holds the action for every
scope, because which one a call needs depends on the id it passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel

from sbomify.apps.core.cle_schemas import CLEEventResponseSchema, CLESupportDefinitionResponseSchema

from .. import serializers
from ..auth import Principal
from ._base import clamp_page, mcp_tool, not_found, resolve_workspace, run_db, unwrap_view
from .catalog import _lookup_component, _lookup_product, _lookup_release

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# The REST view names for each scope: list events, get one event, list support
# definitions.
_VIEWS: dict[str, tuple[str, str, str]] = {
    "product_id": (
        "list_cle_events",
        "get_cle_event",
        "list_cle_support_definitions",
    ),
    "component_id": (
        "list_component_cle_events",
        "get_component_cle_event",
        "list_component_cle_support_definitions",
    ),
    "release_id": (
        "list_release_cle_events",
        "get_release_cle_event",
        "list_release_cle_support_definitions",
    ),
    "component_release_id": (
        "list_component_release_cle_events",
        "get_component_release_cle_event",
        "list_component_release_cle_support_definitions",
    ),
}

_READS = ("product:read", ("component:read_internal", "release:read"))


def _scope(
    principal: Principal,
    product_id: str | None,
    component_id: str | None,
    release_id: str | None,
    component_release_id: str | None,
) -> tuple[str, str]:
    """The one scope a call names, confined to the caller's workspace."""
    from sbomify.apps.core.models import ComponentRelease

    given = [
        (kind, value)
        for kind, value in (
            ("product_id", product_id),
            ("component_id", component_id),
            ("release_id", release_id),
            ("component_release_id", component_release_id),
        )
        if value
    ]
    if len(given) != 1:
        raise ToolError("Pass exactly one of product_id, component_id, release_id or component_release_id.")
    kind, identifier = given[0]

    if kind == "product_id":
        _lookup_product(principal, identifier)
    elif kind == "component_id":
        _lookup_component(principal, identifier)
    elif kind == "release_id":
        _lookup_release(principal, identifier)
    elif not ComponentRelease.objects.filter(pk=identifier, component__team=resolve_workspace(principal)).exists():
        raise not_found("component release", identifier)
    return kind, identifier


def _view(kind: str, index: int) -> Any:
    from sbomify.apps.core import cle_apis

    return getattr(cle_apis, _VIEWS[kind][index])


def _payload(result: tuple[int, Any], *, action: str) -> Any:
    """The view's payload, or its refusal as a ``ToolError``."""
    if result[0] >= 400:
        unwrap_view(result, action=action)
    return result[1]


def _json(row: Any, schema: type[BaseModel]) -> dict[str, Any]:
    return serializers.compact(schema.model_validate(row).model_dump(mode="json"))


def _page(
    principal: Principal,
    scope: tuple[str | None, str | None, str | None, str | None],
    index: int,
    schema: type[BaseModel],
    page: int,
    page_size: int,
    *,
    action: str,
) -> dict[str, Any]:
    kind, identifier = _scope(principal, *scope)
    safe_page, safe_size = clamp_page(page, page_size)
    # One row past the page says whether another page exists; the views return
    # a slice and no total.
    result = _view(kind, index)(
        principal.request, identifier, page_offset=(safe_page - 1) * safe_size, page_size=safe_size + 1
    )
    rows = [_json(row, schema) for row in _payload(result, action=action)]
    return {"items": rows[:safe_size], "page": safe_page, "page_size": safe_size, "has_more": len(rows) > safe_size}


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "list_lifecycle_events", _READS[0], also_requires=_READS[1])
    async def list_lifecycle_events(
        principal: Principal,
        product_id: str | None = None,
        component_id: str | None = None,
        release_id: str | None = None,
        component_release_id: str | None = None,
        event_id: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List the lifecycle events (released, end of support, end of life and so on), newest first.

        Pass exactly one of `product_id`, `component_id`, `release_id` or
        `component_release_id`. Pass `event_id` as well to read one event. A
        `withdrawn` event voids the event named in its `withdrawn_event_id`.
        """

        def query() -> dict[str, Any]:
            scope = (product_id, component_id, release_id, component_release_id)
            if event_id is None:
                return _page(principal, scope, 0, CLEEventResponseSchema, page, page_size, action="Listing events")
            kind, identifier = _scope(principal, *scope)
            result = _view(kind, 1)(principal.request, identifier, event_id)
            return _json(_payload(result, action="Reading the event"), CLEEventResponseSchema)

        return await run_db(query)

    @mcp_tool(mcp, "list_support_definitions", _READS[0], also_requires=_READS[1])
    async def list_support_definitions(
        principal: Principal,
        product_id: str | None = None,
        component_id: str | None = None,
        release_id: str | None = None,
        component_release_id: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List the support definitions (the named support levels lifecycle events refer to by `support_id`).

        Pass exactly one of `product_id`, `component_id`, `release_id` or
        `component_release_id`.
        """

        def query() -> dict[str, Any]:
            scope = (product_id, component_id, release_id, component_release_id)
            return _page(
                principal, scope, 2, CLESupportDefinitionResponseSchema, page, page_size, action="Listing definitions"
            )

        return await run_db(query)

    @mcp_tool(mcp, "get_product_eol_readiness", "product:read")
    async def get_product_eol_readiness(principal: Principal, product_id: str) -> dict[str, Any]:
        """Check whether a product can reach end of life with the CRA checklist met.

        Reports the end of support and end of life dates, whether customers got
        enough notice, the critical and high vulnerabilities neither fixed nor
        risk-accepted, and whether a final SBOM and VEX exist. `is_ready` is the
        verdict and `problems` says what stands in the way.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.core import apis

            _lookup_product(principal, product_id)
            payload = unwrap_view(
                apis.get_product_eol_readiness(principal.request, product_id), action="End-of-life readiness"
            )
            for field in ("unresolved_critical", "unresolved_high"):
                serializers.cut(payload, field)
            return payload

        return await run_db(query)
