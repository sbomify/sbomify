"""Assessment, plugin and crypto inventory tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal, require
from ..limits import enforce_parse_size, enforce_stored_size
from ._base import DETAIL_COLLECTION_LIMIT, clamp_page, mcp_tool, not_found, resolve_workspace, run_db, unwrap_view
from .artifacts import _bounded, _get_artifact

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def lookup_artifact(principal: Principal, artifact_id: str) -> None:
    """Confine ``artifact_id`` to the caller's workspace, with no action check.

    A write tool's own action is checked by the view it delegates to, so this
    must not also demand a read scope the caller may not hold.
    """
    from sbomify.apps.sboms.models import SBOM

    team = resolve_workspace(principal)
    if not SBOM.objects.filter(pk=artifact_id, component__team=team).exists():
        raise not_found("Artifact", artifact_id)


def register_tools(mcp: FastMCP) -> None:
    # also_requires component:access: the inventory service checks it on top of
    # the sbom:read this tool's lookup does, so a token holding only sbom:read
    # would be shown a tool that is certain to refuse it.
    @mcp_tool(mcp, "get_crypto_inventory", "sbom:read", also_requires=("component:access",))
    async def get_crypto_inventory(
        principal: Principal,
        artifact_id: str,
        asset_type: str | None = None,
        pqc_status: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """The cryptographic assets (CBOM inventory) an artifact declares: algorithms, keys, certificates, protocols.

        Returns the totals by asset type and post-quantum readiness, then the
        assets a page at a time. `asset_type` (algorithm, certificate, protocol,
        related-crypto-material) and `pqc_status` (as reported in `pqc_counts`)
        narrow the assets. An artifact with no crypto assets returns an empty
        inventory.
        """

        def query() -> dict[str, Any]:
            from botocore.exceptions import BotoCoreError, ClientError

            from sbomify.apps.core.object_store import StorageClient
            from sbomify.apps.sboms.services.sboms import get_crypto_inventory as inventory_for

            obj = _get_artifact(principal, artifact_id)
            raw: bytes | None = None
            if obj.sbom_filename:
                store = StorageClient("SBOMS")
                try:
                    # The size first, so an oversized artifact is refused before
                    # its transfer; then the bytes, so what gets parsed is bounded
                    # by memory as well as by size.
                    enforce_stored_size(store.get_sbom_size(obj.sbom_filename), artifact_id=artifact_id)
                    raw = store.get_sbom_data(obj.sbom_filename)
                except (ClientError, BotoCoreError) as exc:
                    raise ToolError(
                        f"Artifact {artifact_id} could not be read from storage, so it was not inspected."
                    ) from exc
                enforce_parse_size(raw, artifact_id=artifact_id)
            result = inventory_for(principal.request, artifact_id, raw=raw)
            if not result.ok:
                raise ToolError(f"Crypto inventory failed ({result.status_code or 400}): {result.error}")
            data = result.value or {}

            assets = [
                asset
                for asset in data.get("assets") or []
                if (asset_type is None or asset.get("asset_type") == asset_type)
                and (pqc_status is None or asset.get("pqc_status") == pqc_status)
            ]
            safe_page, safe_size = clamp_page(page, page_size)
            start = (safe_page - 1) * safe_size
            inventory = serializers.paginated(
                [serializers.compact(_bounded(asset)) for asset in assets[start : start + safe_size]],
                page=safe_page,
                page_size=safe_size,
                total=len(assets),
            )
            return serializers.cut(
                {
                    "artifact_id": artifact_id,
                    "count": data.get("count", 0),
                    "by_asset_type": data.get("by_asset_type") or {},
                    "pqc_overall": data.get("pqc_overall"),
                    "pqc_counts": data.get("pqc_counts") or {},
                    "edges": [_bounded(edge) for edge in data.get("edges") or []],
                    "assets": inventory,
                },
                "edges",
            )

        return await run_db(query)

    @mcp_tool(mcp, "rerun_assessment", "component:manage", writes=True, idempotent=False)
    async def rerun_assessment(principal: Principal, artifact_id: str, plugin_name: str) -> dict[str, Any]:
        """Queue a fresh run of one assessment plugin against an artifact.

        Use it after fixing a plugin's configuration or recovering from an
        outage, rather than uploading the artifact again. `plugin_name` is one
        `list_plugins` reports as enabled. The run happens in the background;
        `get_assessments` shows its result once it finishes.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.plugins.apis import rerun_assessment as view

            lookup_artifact(principal, artifact_id)
            queued = unwrap_view(view(principal.request, artifact_id, plugin_name), action="Assessment re-run")
            return {"artifact_id": artifact_id, "plugin_name": plugin_name, "status": queued.get("status")}

        return await run_db(call)

    @mcp_tool(mcp, "list_plugins", "workspace:read")
    async def list_plugins(principal: Principal) -> dict[str, Any]:
        """The assessment plugins sbomify offers, and which this workspace has turned on.

        `enabled` says the workspace runs the plugin on its artifacts.
        `has_access` is false where the workspace's plan does not include it.
        Plugin settings are changed in sbomify, not here.
        """

        def query() -> dict[str, Any]:
            from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings
            from sbomify.apps.plugins.services.access import team_has_plugin_access

            team = resolve_workspace(principal)
            require(principal, "workspace:read", team)
            settings = TeamPluginSettings.objects.filter(team=team).first()
            plugins = RegisteredPlugin.objects.filter(is_enabled=True).order_by("name")
            items = [
                serializers.compact(
                    {
                        "name": plugin.name,
                        "display_name": plugin.display_name,
                        "description": plugin.description,
                        "category": plugin.category,
                        "is_beta": plugin.is_beta,
                        "enabled": settings is not None and settings.is_plugin_enabled(plugin.name),
                        "has_access": team_has_plugin_access(team, plugin.name),
                    }
                )
                for plugin in plugins[:DETAIL_COLLECTION_LIMIT]
            ]
            return {
                "workspace": team.key,
                "plugins": serializers.capped(items, total=plugins.count(), limit=DETAIL_COLLECTION_LIMIT),
            }

        return await run_db(query)
