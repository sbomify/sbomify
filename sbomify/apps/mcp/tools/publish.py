"""Artifact publishing tools: upload SBOMs and VEX, cut and tag releases.

These tools **call the existing REST view functions directly** rather than
reimplementing their logic. Django Ninja's route decorators return the
undecorated function, so ``apis.sbom_upload_cyclonedx(request, component_id)``
is an ordinary call that returns ``(status, payload)``.

That matters more here than anywhere else in this app. The upload path carries
CycloneDX/SPDX schema validation across several spec versions, CBOM
auto-detection, PURL qualifier extraction, the duplicate-artifact guard, S3
upload with orphan cleanup, workspace broadcast, and VEX re-application. A
parallel implementation would drift from it within a release and quietly accept
artifacts the REST API rejects.

The stub ``HttpRequest`` from ``auth`` carries the token record, so the
``can()`` checks inside those views enforce exactly the scopes they always have
— including the OIDC bot's component binding.

ADR-004 holds throughout: artifacts are stored byte-for-byte as supplied.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from ..auth import Principal
from ..limits import enforce_upload_size
from ._base import mcp_tool, not_found, run_db, unwrap_view
from .catalog import _lookup_component, _lookup_product, _lookup_release

if TYPE_CHECKING:
    from django.http import HttpRequest
    from mcp.server.fastmcp import FastMCP


def _with_body(principal: Principal, raw: bytes) -> HttpRequest:
    """The principal's stub request, primed with ``raw`` as its body.

    ``HttpRequest.body`` returns ``self._body`` when set, so assigning it avoids
    needing a real input stream.
    """
    request = principal.request
    request._body = raw
    request.method = "POST"
    return request


def _parse_json(content: str, *, label: str) -> bytes:
    """Validate ``content`` is JSON, size-check it, and return the bytes to store.

    Re-encoding is deliberately avoided — the stored artifact must be
    byte-identical to what the caller supplied (ADR-004), and the SHA-256 the
    upload path computes has to match what the caller can verify independently.

    The size check runs before parsing so an oversized payload is refused
    without first being deserialized into memory.
    """
    raw = content.encode("utf-8")
    enforce_upload_size(raw, label=label)
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"{label} is not valid JSON: {exc}") from exc
    return raw


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "upload_sbom", "artifact:publish", writes=True)
    async def upload_sbom(
        principal: Principal,
        component_id: str,
        content: str,
        sbom_format: str = "cyclonedx",
    ) -> dict[str, Any]:
        """Upload an SBOM to a component.

        `content` is the full SBOM document as a JSON string, stored exactly as
        given. `sbom_format` is "cyclonedx" or "spdx"; the spec version is
        detected from the document.

        Returns the new SBOM's id. Re-uploading an SBOM with the same version
        and format fails as a duplicate — that is expected, not a transient
        error to retry.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.sboms import apis

            normalised = sbom_format.strip().lower()
            if normalised not in ("cyclonedx", "spdx"):
                raise ToolError(f"Unsupported sbom_format {sbom_format!r}; expected 'cyclonedx' or 'spdx'.")

            # Confine the write to the caller's workspace before delegating. The
            # REST view looks the component up globally and leans on can(); for a
            # legacy token with team IS NULL that applies no workspace
            # restriction, so an id from a sibling workspace would be writable
            # even though every read tool reports it as not found.
            _lookup_component(principal, component_id)
            request = _with_body(principal, _parse_json(content, label="SBOM"))
            view = apis.sbom_upload_cyclonedx if normalised == "cyclonedx" else apis.sbom_upload_spdx
            return unwrap_view(view(request, component_id), action="SBOM upload")

        return await run_db(call)

    # also_requires artifact:publish: the view checks it before publish_vex
    # (and the CycloneDX-JSON branch delegates into the SBOM upload view, which
    # checks it too), so a publish_vex-only token would be advertised a tool
    # that is certain to 403.
    @mcp_tool(mcp, "upload_vex", "artifact:publish_vex", also_requires=("artifact:publish",), writes=True)
    async def upload_vex(principal: Principal, component_id: str, content: str) -> dict[str, Any]:
        """Upload a CycloneDX VEX document to a component.

        A VEX re-annotates which vulnerabilities actually affect the component,
        so uploading one changes the workspace's reported vulnerability posture.
        Unlike SBOMs, VEX documents are not subject to the duplicate guard —
        they are expected to be re-issued against the same release.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.sboms import apis

            _lookup_component(principal, component_id)
            request = _with_body(principal, _parse_json(content, label="VEX document"))
            return unwrap_view(apis.vex_artifact_upload(request, component_id), action="VEX upload")

        return await run_db(call)

    @mcp_tool(mcp, "create_release", "release:create", writes=True)
    async def create_release(
        principal: Principal,
        product_id: str,
        name: str,
        version: str | None = None,
        description: str = "",
        is_prerelease: bool = False,
    ) -> dict[str, Any]:
        """Cut a new release for a product.

        Creates the release only; attach artifacts to it with
        `tag_artifact_to_release`.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ReleaseCreateSchema

            # Deliberately a workspace-scoped lookup, not _get_product: the
            # `publish` preset grants release:create but NOT product:read, so
            # requiring the read action here would make this tool advertised-
            # but-always-denied for exactly the token it exists to serve. The
            # view's own can(request, "release:create", product) authorizes.
            _lookup_product(principal, product_id)
            payload = ReleaseCreateSchema(
                name=name,
                version=version,
                description=description,
                is_prerelease=is_prerelease,
                product_id=product_id,
            )
            return unwrap_view(apis.create_release(principal.request, payload), action="Release creation")

        return await run_db(call)

    @mcp_tool(mcp, "tag_artifact_to_release", "release:tag", writes=True)
    async def tag_artifact_to_release(
        principal: Principal,
        release_id: str,
        sbom_id: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach an existing SBOM or document to a release.

        Pass exactly one of `sbom_id` or `document_id`. Artifacts cannot be added
        to the automatic "latest" release.
        """

        def call() -> dict[str, Any]:
            from sbomify.apps.core import apis
            from sbomify.apps.core.schemas import ReleaseArtifactCreateSchema
            from sbomify.apps.documents.models import Document
            from sbomify.apps.sboms.models import SBOM

            if bool(sbom_id) == bool(document_id):
                raise ToolError("Pass exactly one of sbom_id or document_id.")

            # Workspace-scoped lookup only. This tool is declared release:tag,
            # which is what add_artifacts_to_release checks; requiring
            # release:read on top would refuse a token scoped to just release:tag.
            release_obj = _lookup_release(principal, release_id)

            # Resolve the artifact id here too: the view answers an unknown one
            # with a generic 400 ("Error processing SBOM") that reads like a
            # server fault and invites retries. Same uniform not-found as every
            # other tool, whether the id is misspelled or from another workspace.
            team_id = release_obj.product.team_id
            if sbom_id and not SBOM.objects.filter(pk=sbom_id, component__team_id=team_id).exists():
                raise not_found("SBOM", sbom_id)
            if document_id and not Document.objects.filter(pk=document_id, component__team_id=team_id).exists():
                raise not_found("document", document_id)

            payload = ReleaseArtifactCreateSchema(sbom_id=sbom_id, document_id=document_id)
            return unwrap_view(
                apis.add_artifacts_to_release(principal.request, release_id, payload),
                action="Artifact tagging",
            )

        return await run_db(call)
