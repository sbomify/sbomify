"""Workspace contact-profile tools.

A contact profile is the reusable supplier/manufacturer/author record a
workspace attaches to components; it is what populates the supplier and author
fields of a generated CycloneDX document, and therefore what decides whether an
SBOM satisfies NTIA minimum elements. Filling these in is tedious, repetitive,
and exactly the kind of work worth handing to an agent.

Like the publishing tools, these call the existing REST view functions rather
than reimplementing them: the create/update path upserts entities and their
contacts with non-obvious defaulting (owner email fallback, author derivation),
and a second implementation would drift.

The write tools require ``workspace:manage`` / ``component:manage``, neither of
which is in the ``read_only`` or ``publish`` presets — a token must be scoped
for profile management explicitly. Deletion is deliberately not exposed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal, require
from ._base import mcp_tool, not_found, resolve_workspace, run_db, unwrap_view, workspace_key
from .catalog import _lookup_component

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _profile_summary(payload: Any) -> dict[str, Any]:
    """Trim the REST serializer's output to what an agent needs.

    The full schema carries entities, their contacts, and a parallel set of
    legacy flat fields — three views of the same data. Emitting all of it
    triples the token cost and invites the model to reason about the wrong copy.
    """
    data = payload if isinstance(payload, dict) else payload.dict()
    entities = [
        serializers.compact(
            {
                "name": entity.get("name"),
                "email": entity.get("email"),
                "phone": entity.get("phone"),
                "address": entity.get("address"),
                "website_urls": entity.get("website_urls"),
                "is_manufacturer": entity.get("is_manufacturer"),
                "is_supplier": entity.get("is_supplier"),
                "contacts": [
                    serializers.compact({"name": c.get("name"), "email": c.get("email"), "phone": c.get("phone")})
                    for c in entity.get("contacts", []) or []
                ],
            }
        )
        for entity in data.get("entities", []) or []
    ]
    return serializers.compact(
        {
            "id": data.get("id"),
            "name": data.get("name"),
            "is_default": data.get("is_default"),
            "entities": entities,
        }
    )


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "list_contact_profiles", "workspace:read")
    async def list_contact_profiles(principal: Principal) -> dict[str, Any]:
        """List the workspace's contact profiles.

        Use this to find an existing profile before creating a new one — most
        workspaces want a handful of shared profiles, not one per component.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.teams.models import ContactProfile

            team = resolve_workspace(principal)
            require(principal, "workspace:read", team)
            # is_component_private=False like the REST list view: private
            # profiles are per-component bookkeeping rows, and the assignment
            # view refuses them — listing them here would advertise profiles
            # that assign_contact_profile is certain to 404 on.
            profiles = (
                ContactProfile.objects.filter(team=team, is_component_private=False)
                .prefetch_related("entities__contacts")
                .order_by("name")
            )

            from sbomify.apps.teams.apis import serialize_contact_profile

            return {
                "workspace": team.key,
                "profiles": [_profile_summary(serialize_contact_profile(p).dict()) for p in profiles],
            }

        return await run_db(query)

    @mcp_tool(mcp, "get_contact_profile", "workspace:read")
    async def get_contact_profile(principal: Principal, profile_id: str) -> dict[str, Any]:
        """Full detail for one contact profile."""

        def query() -> dict[str, Any]:
            from sbomify.apps.teams.apis import serialize_contact_profile
            from sbomify.apps.teams.models import ContactProfile

            team = resolve_workspace(principal)
            require(principal, "workspace:read", team)
            profile = (
                ContactProfile.objects.filter(pk=profile_id, team=team, is_component_private=False)
                .prefetch_related("entities__contacts")
                .first()
            )
            if profile is None:
                raise not_found("contact profile", profile_id)
            return _profile_summary(serialize_contact_profile(profile).dict())

        return await run_db(query)

    @mcp_tool(mcp, "create_contact_profile", "workspace:manage", writes=True)
    async def create_contact_profile(
        principal: Principal,
        name: str,
        email: str,
        supplier_name: str | None = None,
        contact_name: str | None = None,
        phone: str | None = None,
        address: str | None = None,
        website_url: str | None = None,
        is_default: bool = False,
    ) -> dict[str, Any]:
        """Create a workspace contact profile.

        `name` labels the profile inside sbomify; `supplier_name` is the
        organisation that appears in generated SBOMs (defaults to `name`).
        `email` is the contact address published with those SBOMs — it is
        required, because a supplier entry with no reachable contact does not
        satisfy the NTIA minimum elements these profiles exist to fill in.
        `contact_name` names the person or team behind that address (defaults to
        `supplier_name`). Setting `is_default` makes this the profile new
        components inherit.

        Check `list_contact_profiles` first — profiles are meant to be shared
        across components, so a near-duplicate is usually a mistake.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.teams.apis import create_contact_profile as view
            from sbomify.apps.teams.schemas import (
                ContactEntityCreateSchema,
                ContactProfileContactSchema,
                ContactProfileCreateSchema,
            )

            team = resolve_workspace(principal)
            organisation = supplier_name or name
            # An entity with no contacts is rejected by the view, and a contact
            # requires an email — hence email being a required argument rather
            # than an optional one silently producing a 400.
            entity = ContactEntityCreateSchema(
                name=organisation,
                email=email,
                phone=phone,
                address=address,
                website_urls=[website_url] if website_url else [],
                is_supplier=True,
                is_manufacturer=True,
                contacts=[
                    ContactProfileContactSchema(
                        name=contact_name or organisation,
                        email=email,
                        phone=phone,
                    )
                ],
            )
            payload = ContactProfileCreateSchema(name=name, entities=[entity], is_default=is_default)
            created = unwrap_view(
                view(principal.request, workspace_key(team), payload), action="Contact profile creation"
            )
            return _profile_summary(created)

        return await run_db(call)

    @mcp_tool(mcp, "update_contact_profile", "workspace:manage", writes=True)
    async def update_contact_profile(
        principal: Principal,
        profile_id: str,
        name: str | None = None,
        is_default: bool | None = None,
    ) -> dict[str, Any]:
        """Rename a contact profile or make it the workspace default.

        Editing the entity details (supplier name, addresses, per-contact
        emails) is not exposed over MCP — that data ends up in published SBOMs,
        so it stays a deliberate action in the web UI.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.teams.apis import update_contact_profile as view
            from sbomify.apps.teams.models import ContactProfile
            from sbomify.apps.teams.schemas import ContactProfileUpdateSchema

            team = resolve_workspace(principal)
            if not ContactProfile.objects.filter(pk=profile_id, team=team, is_component_private=False).exists():
                raise not_found("contact profile", profile_id)

            fields: dict[str, Any] = {}
            if name is not None:
                fields["name"] = name
            if is_default is not None:
                fields["is_default"] = is_default
            if not fields:
                raise ToolError("Nothing to update: pass name and/or is_default.")

            payload = ContactProfileUpdateSchema(**fields)
            updated = unwrap_view(
                view(principal.request, workspace_key(team), profile_id, payload), action="Contact profile update"
            )
            return _profile_summary(updated)

        return await run_db(call)

    @mcp_tool(mcp, "assign_contact_profile", "component:manage", writes=True)
    async def assign_contact_profile(principal: Principal, component_id: str, profile_id: str) -> dict[str, Any]:
        """Attach a contact profile to a component.

        The component's generated SBOMs then carry that profile's supplier and
        author details, which is what NTIA minimum-elements checks look for.
        Use this to fix components flagged as missing supplier information.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core.apis import patch_component_metadata
            from sbomify.apps.sboms.schemas import ComponentMetaDataPatch
            from sbomify.apps.teams.models import ContactProfile

            team = resolve_workspace(principal)
            # Workspace-scoped lookup only. This tool is declared component:manage,
            # which is what patch_component_metadata checks; requiring
            # component:read_internal on top would refuse a correctly scoped token.
            component = _lookup_component(principal, component_id)
            if not ContactProfile.objects.filter(pk=profile_id, team=team, is_component_private=False).exists():
                raise not_found("contact profile", profile_id)

            payload = ComponentMetaDataPatch(contact_profile_id=profile_id)
            unwrap_view(
                patch_component_metadata(principal.request, component_id, payload),
                action="Contact profile assignment",
            )
            return {"component_id": component.id, "contact_profile_id": profile_id, "assigned": True}

        return await run_db(call)
