"""Lifecycle (CLE) and end-of-life readiness tools.

Lifecycle events follow ECMA-428 and are append-only: nothing here edits or
deletes one. A ``withdrawn`` event is how an earlier event is voided.

Events and support definitions hang off four kinds of thing: a product, a
component, a product release and a component release. Each tool takes exactly
one of the four ids and delegates to that scope's REST view, so the checks
those views make are the checks these tools make.

A token is shown a lifecycle tool only when it holds the action for every
scope, because which one a call needs depends on the id it passes.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from sbomify.apps.core.cle_schemas import (
    CLE_EVENT_TYPES,
    CLEEventCreateSchema,
    CLEEventResponseSchema,
    CLEIdentifierSchema,
    CLESupportDefinitionCreateSchema,
    CLESupportDefinitionResponseSchema,
    CLEVersionSpecifierSchema,
)

from .. import serializers
from ..auth import Principal
from ._base import clamp_page, mcp_tool, not_found, resolve_workspace, run_db, unwrap_view
from .catalog import _lookup_component, _lookup_product, _lookup_release

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# The REST view names for each scope: list events, get one event, create an
# event, list support definitions, create a support definition.
_VIEWS: dict[str, tuple[str, str, str, str, str]] = {
    "product_id": (
        "list_cle_events",
        "get_cle_event",
        "create_cle_event_endpoint",
        "list_cle_support_definitions",
        "create_cle_support_definition_endpoint",
    ),
    "component_id": (
        "list_component_cle_events",
        "get_component_cle_event",
        "create_component_cle_event_endpoint",
        "list_component_cle_support_definitions",
        "create_component_cle_support_definition_endpoint",
    ),
    "release_id": (
        "list_release_cle_events",
        "get_release_cle_event",
        "create_release_cle_event_endpoint",
        "list_release_cle_support_definitions",
        "create_release_cle_support_definition_endpoint",
    ),
    "component_release_id": (
        "list_component_release_cle_events",
        "get_component_release_cle_event",
        "create_component_release_cle_event_endpoint",
        "list_component_release_cle_support_definitions",
        "create_component_release_cle_support_definition_endpoint",
    ),
}

_READS = ("product:read", ("component:read_internal", "release:read"))
_WRITES = ("product:manage", ("component:manage", "release:manage"))


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
                principal, scope, 3, CLESupportDefinitionResponseSchema, page, page_size, action="Listing definitions"
            )

        return await run_db(query)

    @mcp_tool(mcp, "create_lifecycle_event", _WRITES[0], also_requires=_WRITES[1], writes=True, idempotent=False)
    async def create_lifecycle_event(
        principal: Principal,
        event_type: CLE_EVENT_TYPES,
        effective: datetime,
        product_id: str | None = None,
        component_id: str | None = None,
        release_id: str | None = None,
        component_release_id: str | None = None,
        version: str = "",
        versions: list[CLEVersionSpecifierSchema] | None = None,
        support_id: str = "",
        license: str = "",
        superseded_by_version: str = "",
        identifiers: list[CLEIdentifierSchema] | None = None,
        withdrawn_event_id: int | None = None,
        reason: str = "",
        description: str = "",
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record a lifecycle event, such as a release or an end of support date.

        Pass exactly one of `product_id`, `component_id`, `release_id` or
        `component_release_id`. `effective` is when the event takes effect, with
        a timezone (for example 2027-01-01T00:00:00Z). `versions` lists the
        versions it covers, each a `version` or a `range`. Events cannot be
        edited or deleted: to take one back, record a `withdrawn` event with its
        `withdrawn_event_id`. Each event type needs its own fields, and the
        error names any that are missing.
        """

        def call() -> dict[str, Any]:
            kind, identifier = _scope(principal, product_id, component_id, release_id, component_release_id)
            try:
                payload = CLEEventCreateSchema(
                    event_type=event_type,
                    effective=effective,
                    version=version,
                    versions=versions or [],
                    support_id=support_id,
                    license=license,
                    superseded_by_version=superseded_by_version,
                    identifiers=identifiers or [],
                    withdrawn_event_id=withdrawn_event_id,
                    reason=reason,
                    description=description,
                    references=references or [],
                )
            except ValidationError as exc:
                raise ToolError(f"Invalid event: {exc}") from exc
            result = _view(kind, 2)(principal.request, identifier, payload)
            return _json(_payload(result, action="Recording the event"), CLEEventResponseSchema)

        return await run_db(call)

    @mcp_tool(mcp, "create_support_definition", _WRITES[0], also_requires=_WRITES[1], writes=True, idempotent=False)
    async def create_support_definition(
        principal: Principal,
        support_id: str,
        description: str,
        product_id: str | None = None,
        component_id: str | None = None,
        release_id: str | None = None,
        component_release_id: str | None = None,
        url: str = "",
    ) -> dict[str, Any]:
        """Define a support level, such as "standard" or "lts", that lifecycle events can name.

        Pass exactly one of `product_id`, `component_id`, `release_id` or
        `component_release_id`. `support_id` must be new in that scope. `url`,
        if given, points at the published support policy.
        """

        def call() -> dict[str, Any]:
            kind, identifier = _scope(principal, product_id, component_id, release_id, component_release_id)
            try:
                payload = CLESupportDefinitionCreateSchema(support_id=support_id, description=description, url=url)
            except ValidationError as exc:
                raise ToolError(f"Invalid support definition: {exc}") from exc
            result = _view(kind, 4)(principal.request, identifier, payload)
            return _json(_payload(result, action="Creating the definition"), CLESupportDefinitionResponseSchema)

        return await run_db(call)

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
