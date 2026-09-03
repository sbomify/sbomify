"""Catalog navigation tools: workspace, products, components, releases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import serializers
from ..auth import Principal, require
from ._base import clamp_page, mcp_tool, not_found, resolve_workspace, run_db

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


# ``_lookup_*`` resolve a resource **within the caller's workspace** and raise a
# uniform not-found otherwise. They perform no action check, so a write tool can
# confine itself to its own workspace without also demanding a read scope the
# caller may not have (a `publish` token has no `product:read`). The action check
# is still made — by the tool, or by the REST view it delegates to.
#
# ``_get_*`` add the read-action check on top, for the read tools.


def _lookup_product(principal: Principal, product_id: str) -> Any:
    from sbomify.apps.core.models import Product

    team = resolve_workspace(principal)
    obj = Product.objects.filter(pk=product_id, team=team).first()
    if obj is None:
        raise not_found("product", product_id)
    return obj


def _lookup_component(principal: Principal, component_id: str) -> Any:
    from sbomify.apps.core.models import Component

    team = resolve_workspace(principal)
    obj = Component.objects.filter(pk=component_id, team=team).first()
    if obj is None:
        raise not_found("component", component_id)
    return obj


def _lookup_release(principal: Principal, release_id: str) -> Any:
    from sbomify.apps.core.models import Release

    team = resolve_workspace(principal)
    obj = Release.objects.filter(pk=release_id, product__team=team).select_related("product").first()
    if obj is None:
        raise not_found("release", release_id)
    return obj


def _get_product(principal: Principal, product_id: str) -> Any:
    obj = _lookup_product(principal, product_id)
    require(principal, "product:read", obj)
    return obj


def _get_component(principal: Principal, component_id: str) -> Any:
    obj = _lookup_component(principal, component_id)
    require(principal, "component:read_internal", obj)
    return obj


def _get_release(principal: Principal, release_id: str) -> Any:
    obj = _lookup_release(principal, release_id)
    require(principal, "release:read", obj.product)
    return obj


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "get_workspace_summary", "workspace:read")
    async def get_workspace_summary(principal: Principal) -> dict[str, Any]:
        """Orient yourself in the current workspace.

        Returns the workspace name and counts of products, components, SBOMs and
        documents. Call this first when you do not yet know what the workspace
        contains.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.core.models import Component, Product
            from sbomify.apps.documents.models import Document
            from sbomify.apps.sboms.models import SBOM

            team = resolve_workspace(principal)
            require(principal, "workspace:read", team)
            return {
                "workspace": {"key": team.key, "name": team.name},
                "counts": {
                    "products": Product.objects.filter(team=team).count(),
                    "components": Component.objects.filter(team=team).count(),
                    "sboms": SBOM.objects.filter(component__team=team).count(),
                    "documents": Document.objects.filter(component__team=team).count(),
                },
            }

        return await run_db(query)

    @mcp_tool(mcp, "list_products", "product:read")
    async def list_products(principal: Principal, page: int = 1, page_size: int = 25) -> dict[str, Any]:
        """List the products in the current workspace, newest first."""

        def query() -> dict[str, Any]:
            from sbomify.apps.core.models import Product

            team = resolve_workspace(principal)
            require(principal, "product:read", team)
            safe_page, safe_size = clamp_page(page, page_size)
            queryset = Product.objects.filter(team=team).order_by("-created_at")
            rows, total = serializers.page_queryset(queryset, safe_page, safe_size)
            return serializers.paginated(
                [serializers.product(row) for row in rows],
                page=safe_page,
                page_size=safe_size,
                total=total,
            )

        return await run_db(query)

    @mcp_tool(mcp, "get_product", "product:read")
    async def get_product(principal: Principal, product_id: str) -> dict[str, Any]:
        """Full detail for one product, including its components and identifiers.

        Folds together what would otherwise be three separate calls.
        """

        def query() -> dict[str, Any]:
            obj = _get_product(principal, product_id)
            data = serializers.product(obj, detail=True)
            data["components"] = [serializers.component(c) for c in obj.components.all().order_by("name")]
            data["identifiers"] = [
                serializers.compact({"type": i.identifier_type, "value": i.value}) for i in obj.identifiers.all()
            ]
            data["links"] = [
                serializers.compact({"type": link.link_type, "url": link.url, "title": link.title})
                for link in obj.links.all()
            ]
            return serializers.compact(data)

        return await run_db(query)

    @mcp_tool(mcp, "list_components", "component:read_internal")
    async def list_components(
        principal: Principal,
        product_id: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List components in the workspace, optionally limited to one product."""

        def query() -> dict[str, Any]:
            from sbomify.apps.core.models import Component

            team = resolve_workspace(principal)
            require(principal, "component:read_internal", team)
            queryset = Component.objects.filter(team=team)
            if product_id is not None:
                # Workspace-scoped lookup only: the tool's declared action is
                # component:read_internal, and get_component already exposes a
                # component's product names under that scope — demanding
                # product:read for the filter would advertise-then-refuse a
                # token scoped to exactly the declared action.
                _lookup_product(principal, product_id)
                queryset = queryset.filter(products__id=product_id)
            safe_page, safe_size = clamp_page(page, page_size)
            rows, total = serializers.page_queryset(queryset.order_by("name"), safe_page, safe_size)
            return serializers.paginated(
                [serializers.component(row) for row in rows],
                page=safe_page,
                page_size=safe_size,
                total=total,
            )

        return await run_db(query)

    @mcp_tool(mcp, "get_component", "component:read_internal")
    async def get_component(principal: Principal, component_id: str) -> dict[str, Any]:
        """Full detail for one component, with its most recent SBOMs and documents."""

        def query() -> dict[str, Any]:
            from sbomify.apps.documents.models import Document
            from sbomify.apps.sboms.models import SBOM

            obj = _get_component(principal, component_id)
            data = serializers.component(obj, detail=True)
            data["products"] = [{"id": p.id, "name": p.name} for p in obj.products.all()]
            data["recent_sboms"] = [
                serializers.sbom(s) for s in SBOM.objects.filter(component=obj).order_by("-created_at")[:10]
            ]
            data["recent_documents"] = [
                serializers.document(d) for d in Document.objects.filter(component=obj).order_by("-created_at")[:10]
            ]
            return serializers.compact(data)

        return await run_db(query)

    @mcp_tool(mcp, "list_releases", "release:read")
    async def list_releases(
        principal: Principal,
        product_id: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List releases in the workspace, newest first, optionally for one product."""

        def query() -> dict[str, Any]:
            from sbomify.apps.core.models import Release

            team = resolve_workspace(principal)
            require(principal, "release:read", team)
            queryset = Release.objects.filter(product__team=team)
            if product_id is not None:
                # Workspace-scoped lookup only, for the same reason as
                # list_components: release:read is this tool's declared action,
                # and every release row already names its product.
                _lookup_product(principal, product_id)
                queryset = queryset.filter(product_id=product_id)
            safe_page, safe_size = clamp_page(page, page_size)
            rows, total = serializers.page_queryset(queryset.order_by("-created_at"), safe_page, safe_size)
            return serializers.paginated(
                [serializers.release(row) for row in rows],
                page=safe_page,
                page_size=safe_size,
                total=total,
            )

        return await run_db(query)

    @mcp_tool(mcp, "get_release", "release:read")
    async def get_release(principal: Principal, release_id: str) -> dict[str, Any]:
        """Full detail for one release, including every artifact tagged to it."""

        def query() -> dict[str, Any]:
            obj = _get_release(principal, release_id)
            data = serializers.release(obj, detail=True)
            data["product"] = {"id": obj.product.id, "name": obj.product.name}
            data["artifacts"] = [
                serializers.release_artifact(a) for a in obj.artifacts.select_related("sbom", "document").all()
            ]
            return serializers.compact(data)

        return await run_db(query)
