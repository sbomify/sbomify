"""Product, component and release editing tools.

Like the publishing tools, these call the REST views rather than reimplementing
them, so plan limits, name clashes, the "latest" release guard and the
workspace broadcast behave exactly as they do over REST.

Visibility is never passed through. Who can see a product or component is an
owner's or admin's call, made in the app, and the views would refuse a member's
token anyway. Deletes are absent, as everywhere on this surface.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import serializers
from ..auth import Principal
from ._base import mcp_tool, not_found, resolve_workspace, run_db, unwrap_view
from .catalog import _get_component, _lookup_component, _lookup_product, _lookup_release

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class Contact(BaseModel):
    """A person named on a component: a supplier contact or an author."""

    name: str
    email: str | None = None
    phone: str | None = None


def _schema(schema: type[BaseModel], label: str, **fields: Any) -> Any:
    """Build a REST request schema, answering a validation failure as a refusal the agent can fix."""
    try:
        return schema(**fields)
    except ValidationError as exc:
        raise ToolError(f"Invalid {label}: {exc}") from exc


def _given(**fields: Any) -> dict[str, Any]:
    """The arguments the agent actually passed. A partial update must not send the rest as nulls."""
    given = {key: value for key, value in fields.items() if value is not None}
    if not given:
        raise ToolError(f"Nothing to update: pass at least one of {', '.join(fields)}.")
    return given


def _product(product_id: str) -> dict[str, Any]:
    from sbomify.apps.core.models import Product

    return serializers.product(Product.objects.get(pk=product_id), detail=True)


def _component(component_id: str) -> dict[str, Any]:
    from sbomify.apps.core.models import Component

    return serializers.component(Component.objects.get(pk=component_id), detail=True)


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "create_product", "product:create", writes=True, idempotent=False)
    async def create_product(principal: Principal, name: str, description: str = "") -> dict[str, Any]:
        """Create a product in the current workspace.

        A product groups the components you ship together. Add components to it
        with `add_component_to_product`. Names are unique within a workspace.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ProductCreateSchema

            resolve_workspace(principal)
            payload = _schema(ProductCreateSchema, "product", name=name, description=description)
            created = unwrap_view(apis.create_product(principal.request, payload), action="Product creation")
            return _product(created["id"])

        return await run_db(call)

    @mcp_tool(mcp, "update_product", "product:manage", writes=True, idempotent=True)
    async def update_product(
        principal: Principal,
        product_id: str,
        name: str | None = None,
        description: str | None = None,
        release_date: date | None = None,
        end_of_support: date | None = None,
        end_of_life: date | None = None,
    ) -> dict[str, Any]:
        """Change a product's name, description or lifecycle dates.

        Only the arguments you pass change. Dates are ISO dates (YYYY-MM-DD).
        Whether the product is public is changed in the app, not here.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ProductPatchSchema

            _lookup_product(principal, product_id)
            fields = _given(
                name=name,
                description=description,
                release_date=release_date,
                end_of_support=end_of_support,
                end_of_life=end_of_life,
            )
            payload = _schema(ProductPatchSchema, "product update", **fields)
            unwrap_view(apis.patch_product(principal.request, product_id, payload), action="Product update")
            return _product(product_id)

        return await run_db(call)

    # also_requires component:manage: the patch view checks it on every
    # component it attaches, so a token without it would be shown a tool
    # certain to 403.
    @mcp_tool(
        mcp,
        "add_component_to_product",
        "product:manage",
        also_requires=("component:manage",),
        writes=True,
        idempotent=True,
    )
    async def add_component_to_product(principal: Principal, product_id: str, component_id: str) -> dict[str, Any]:
        """Add a component to a product. The product's other components stay.

        A component must belong to a product before its SBOMs can be scanned
        for vulnerabilities or added to the product's releases.
        """

        def call() -> dict[str, Any]:
            from django.db import transaction

            from sbomify.apps.core import apis
            from sbomify.apps.core.models import Product
            from sbomify.apps.core.schemas import ProductPatchSchema

            product = _lookup_product(principal, product_id)
            component = _lookup_component(principal, component_id)
            # The view replaces the whole set, so send the current set plus the
            # new one. The product row stays locked from the read to the write,
            # so two adds at once cannot each drop the other's component.
            with transaction.atomic():
                Product.objects.select_for_update().get(pk=product.pk)
                current = list(product.components.values_list("id", flat=True))
                if component.id not in current:
                    payload = _schema(ProductPatchSchema, "component list", component_ids=[*current, component.id])
                    unwrap_view(
                        apis.patch_product(principal.request, product_id, payload), action="Adding the component"
                    )
            return {"product_id": product.id, "component_id": component.id, "added": True}

        return await run_db(call)

    @mcp_tool(mcp, "add_product_identifier", "product:manage", writes=True, idempotent=False)
    async def add_product_identifier(
        principal: Principal, product_id: str, identifier_type: str, value: str
    ) -> dict[str, Any]:
        """Add an identifier to a product, such as a CPE, PURL, GTIN, SKU or MPN.

        `identifier_type` is one of: gtin_12, gtin_13, gtin_14, gtin_8, sku, mpn,
        asin, gs1_gpc_brick, cpe, purl. Identifiers are a Business and
        Enterprise feature.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ProductIdentifierCreateSchema

            _lookup_product(principal, product_id)
            payload = _schema(ProductIdentifierCreateSchema, "identifier", identifier_type=identifier_type, value=value)
            return serializers.compact(
                unwrap_view(
                    apis.create_product_identifier(principal.request, product_id, payload),
                    action="Adding the identifier",
                )
            )

        return await run_db(call)

    @mcp_tool(mcp, "update_product_identifier", "product:manage", writes=True, idempotent=True)
    async def update_product_identifier(
        principal: Principal,
        product_id: str,
        identifier_id: str,
        identifier_type: str | None = None,
        value: str | None = None,
    ) -> dict[str, Any]:
        """Change one of a product's identifiers. Only the arguments you pass change.

        Find the `identifier_id` with `get_product`.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ProductIdentifierUpdateSchema

            product = _lookup_product(principal, product_id)
            current = product.identifiers.filter(pk=identifier_id).first()
            if current is None:
                raise not_found("product identifier", identifier_id)
            fields = _given(identifier_type=identifier_type, value=value)
            payload = _schema(
                ProductIdentifierUpdateSchema,
                "identifier",
                identifier_type=fields.get("identifier_type", current.identifier_type),
                value=fields.get("value", current.value),
            )
            return serializers.compact(
                unwrap_view(
                    apis.update_product_identifier(principal.request, product_id, identifier_id, payload),
                    action="Updating the identifier",
                )
            )

        return await run_db(call)

    @mcp_tool(mcp, "add_product_link", "product:manage", writes=True, idempotent=False)
    async def add_product_link(
        principal: Principal,
        product_id: str,
        link_type: str,
        title: str,
        url: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Add a link to a product, such as its website, documentation or security contact page.

        `link_type` is one of: website, support, documentation, repository,
        changelog, release_notes, security, issue_tracker, download, chat,
        social, other.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ProductLinkCreateSchema

            _lookup_product(principal, product_id)
            payload = _schema(
                ProductLinkCreateSchema, "link", link_type=link_type, title=title, url=url, description=description
            )
            return serializers.compact(
                unwrap_view(apis.create_product_link(principal.request, product_id, payload), action="Adding the link")
            )

        return await run_db(call)

    @mcp_tool(mcp, "update_product_link", "product:manage", writes=True, idempotent=True)
    async def update_product_link(
        principal: Principal,
        product_id: str,
        link_id: str,
        link_type: str | None = None,
        title: str | None = None,
        url: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Change one of a product's links. Only the arguments you pass change.

        Find the `link_id` with `get_product`.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ProductLinkUpdateSchema

            product = _lookup_product(principal, product_id)
            current = product.links.filter(pk=link_id).first()
            if current is None:
                raise not_found("product link", link_id)
            fields = _given(link_type=link_type, title=title, url=url, description=description)
            payload = _schema(
                ProductLinkUpdateSchema,
                "link",
                link_type=fields.get("link_type", current.link_type),
                title=fields.get("title", current.title),
                url=fields.get("url", current.url),
                description=fields.get("description", current.description),
            )
            return serializers.compact(
                unwrap_view(
                    apis.update_product_link(principal.request, product_id, link_id, payload),
                    action="Updating the link",
                )
            )

        return await run_db(call)

    @mcp_tool(mcp, "create_component", "component:create", writes=True, idempotent=False)
    async def create_component(principal: Principal, name: str, component_type: str = "bom") -> dict[str, Any]:
        """Create a component in the current workspace.

        `component_type` is "bom" for a component that holds SBOMs and other
        BOMs, or "document" for one that holds documents. The new component
        belongs to no product yet: add it to one with `add_component_to_product`.
        Names are unique within a workspace.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ComponentCreateSchema

            resolve_workspace(principal)
            payload = _schema(ComponentCreateSchema, "component", name=name, component_type=component_type)
            created = unwrap_view(apis.create_component(principal.request, payload), action="Component creation")
            return _component(created["id"])

        return await run_db(call)

    @mcp_tool(mcp, "update_component", "component:manage", writes=True, idempotent=True)
    async def update_component(
        principal: Principal,
        component_id: str,
        name: str | None = None,
        component_type: str | None = None,
    ) -> dict[str, Any]:
        """Rename a component or change its type ("bom" or "document").

        Only the arguments you pass change. Supplier, authors, licenses and
        lifecycle are changed with `update_component_metadata`; who can see the
        component is changed in the app.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ComponentPatchSchema

            _lookup_component(principal, component_id)
            fields = _given(name=name, component_type=component_type)
            payload = _schema(ComponentPatchSchema, "component update", **fields)
            unwrap_view(apis.patch_component(principal.request, component_id, payload), action="Component update")
            return _component(component_id)

        return await run_db(call)

    @mcp_tool(mcp, "get_component_metadata", "component:read_internal")
    async def get_component_metadata(principal: Principal, component_id: str) -> dict[str, Any]:
        """The supplier, manufacturer, authors, licenses and lifecycle details of a component.

        These are what generated SBOMs carry for the component, and what NTIA
        minimum-elements checks look for. When `contact_profile_id` is set, the
        supplier and manufacturer come from that contact profile.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.core import apis

            _get_component(principal, component_id)
            result = apis.get_component_metadata(principal.request, component_id)
            # The view answers a bare schema on success and a (status, body)
            # pair on refusal.
            data = unwrap_view(result if isinstance(result, tuple) else (200, result), action="Component metadata")
            # The full profile is one get_contact_profile call away; inlining it
            # here repeats the supplier and manufacturer already shown.
            data.pop("contact_profile", None)
            for field in ("authors", "licenses"):
                serializers.cut(data, field)
            return serializers.compact(data)

        return await run_db(query)

    @mcp_tool(mcp, "update_component_metadata", "component:manage", writes=True, idempotent=True)
    async def update_component_metadata(
        principal: Principal,
        component_id: str,
        supplier_name: str | None = None,
        supplier_urls: list[str] | None = None,
        supplier_address: str | None = None,
        supplier_contacts: list[Contact] | None = None,
        authors: list[Contact] | None = None,
        licenses: list[str] | None = None,
        lifecycle_phase: str | None = None,
        release_date: date | None = None,
        end_of_support: date | None = None,
        end_of_life: date | None = None,
    ) -> dict[str, Any]:
        """Change a component's supplier, authors, licenses or lifecycle details.

        Only the arguments you pass change, but a list you pass replaces the
        whole list: `supplier_contacts`, `authors` and `licenses` each replace
        what the component has. Read the current values with
        `get_component_metadata` first and send the full list you want.

        `licenses` are SPDX identifiers or expressions, such as "MIT" or
        "Apache-2.0 OR MIT". `lifecycle_phase` is one of: design, pre-build,
        build, post-build, operations, discovery, decommission. Dates are ISO
        dates (YYYY-MM-DD).

        A component with a contact profile takes its supplier from the profile,
        so the supplier arguments only show once it has none. Use
        `assign_contact_profile` to change the profile.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.models import Component
            from sbomify.apps.sboms.schemas import ComponentMetaDataPatch

            component = _lookup_component(principal, component_id)
            fields = _given(
                supplier_name=supplier_name,
                supplier_urls=supplier_urls,
                supplier_address=supplier_address,
                supplier_contacts=supplier_contacts,
                authors=authors,
                licenses=licenses,
                lifecycle_phase=lifecycle_phase,
                release_date=release_date,
                end_of_support=end_of_support,
                end_of_life=end_of_life,
            )

            # The view saves the phase without validating it against the field's choices.
            phases = [value for value, _ in Component._meta.get_field("lifecycle_phase").choices or []]
            if lifecycle_phase is not None and lifecycle_phase not in phases:
                raise ToolError(f"Unknown lifecycle_phase {lifecycle_phase!r}; expected one of {', '.join(phases)}.")

            patch: dict[str, Any] = {
                key: fields[key]
                for key in ("lifecycle_phase", "release_date", "end_of_support", "end_of_life", "licenses")
                if key in fields
            }
            if "authors" in fields:
                patch["authors"] = [author.model_dump(exclude_none=True) for author in fields["authors"]]
            if {"supplier_name", "supplier_urls", "supplier_address", "supplier_contacts"} & fields.keys():
                # The view writes the name, URLs and address together, so one
                # left out would be blanked. Fill them from what is stored.
                supplier: dict[str, Any] = {
                    "name": fields.get("supplier_name", component.supplier_name),
                    "url": fields.get("supplier_urls", component.supplier_url or []),
                    "address": fields.get("supplier_address", component.supplier_address),
                }
                if "supplier_contacts" in fields:
                    supplier["contacts"] = [c.model_dump(exclude_none=True) for c in fields["supplier_contacts"]]
                patch["supplier"] = supplier

            payload = _schema(ComponentMetaDataPatch, "metadata", **patch)
            unwrap_view(
                apis.patch_component_metadata(principal.request, component_id, payload),
                action="Component metadata update",
            )
            return {"component_id": component.id, "updated": sorted(fields)}

        return await run_db(call)

    @mcp_tool(mcp, "update_release", "release:manage", writes=True, idempotent=True)
    async def update_release(
        principal: Principal,
        release_id: str,
        name: str | None = None,
        version: str | None = None,
        description: str | None = None,
        is_prerelease: bool | None = None,
        released_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Change a release's name, version, description, pre-release flag or release date.

        Only the arguments you pass change. `released_at` is an ISO date-time.
        The automatic "latest" release cannot be changed.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.models import Release
            from sbomify.apps.core.schemas import ReleasePatchSchema

            _lookup_release(principal, release_id)
            fields = _given(
                name=name,
                version=version,
                description=description,
                is_prerelease=is_prerelease,
                released_at=released_at,
            )
            payload = _schema(ReleasePatchSchema, "release update", **fields)
            unwrap_view(apis.patch_release(principal.request, release_id, payload), action="Release update")
            return serializers.release(Release.objects.get(pk=release_id), detail=True)

        return await run_db(call)

    @mcp_tool(mcp, "link_release", "release:tag", writes=True, idempotent=False)
    async def link_release(
        principal: Principal,
        release_id: str,
        linked_release_id: str | None = None,
        linked_product_id: str | None = None,
        linked_version: str | None = None,
    ) -> dict[str, Any]:
        """Link a release of another product to this release.

        Use it when this release ships with another product's release, such as
        firmware that bundles a library. The linked release is listed with this
        one and its SBOMs join this release's aggregate SBOM. Nothing is moved
        or copied.

        Name the release to link by `linked_release_id`, or by
        `linked_product_id` and `linked_version` together.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ReleaseLinkCreateSchema

            by_pair = bool(linked_product_id and linked_version)
            if bool(linked_release_id) == by_pair:
                raise ToolError("Pass linked_release_id, or linked_product_id and linked_version together.")
            _lookup_release(principal, release_id)
            if linked_release_id:
                _lookup_release(principal, linked_release_id)
            else:
                _lookup_product(principal, str(linked_product_id))
            payload = ReleaseLinkCreateSchema(
                release_id=linked_release_id, product_id=linked_product_id, version=linked_version
            )
            return serializers.compact(
                unwrap_view(
                    apis.link_release_to_release(principal.request, release_id, payload), action="Linking the release"
                )
            )

        return await run_db(call)
