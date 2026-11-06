"""Artifact signature and provenance tools.

Both attach evidence to an artifact already uploaded, and both delegate to the
REST views, which check the evidence names the artifact's hash, store it, and
queue the verification plugin. An artifact holds one of each: a second upload
is refused rather than replacing the first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django.http import HttpResponse
from mcp.server.fastmcp.exceptions import ToolError

from ..auth import Principal
from ..limits import enforce_upload_size
from ._base import mcp_tool, not_found, resolve_workspace, run_db, unwrap_view
from .documents import decode_base64
from .publish import _with_body

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


def _settle(response: tuple[int, dict[str, Any]] | HttpResponse, *, action: str) -> None:
    """Relay an upload view's refusal. Its HttpResponse branch serves downloads and is never taken here."""
    if isinstance(response, HttpResponse):
        raise ToolError(f"{action} failed ({response.status_code}).")
    unwrap_view(response, action=action)


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "upload_artifact_signature", "sbom:manage", writes=True, idempotent=False)
    async def upload_artifact_signature(
        principal: Principal,
        artifact_id: str,
        content_base64: str,
        signature_type: Literal["cosign-bundle", "pgp-detached", "pkcs7"],
    ) -> dict[str, Any]:
        """Attach a detached signature to an artifact.

        `content_base64` is the signature file, base64-encoded. `signature_type`
        says its format. The signature must be over the artifact as stored. An
        artifact takes one signature; a second upload is refused.
        """
        raw = decode_base64(content_base64, label="Signature")

        def call() -> dict[str, Any]:
            from sbomify.apps.sboms import apis

            lookup_artifact(principal, artifact_id)
            request = _with_body(principal, raw)
            request.META["HTTP_X_SIGNATURE_TYPE"] = signature_type
            request.__dict__.pop("headers", None)
            _settle(apis.upload_signature(request, artifact_id), action="Signature upload")
            return {"artifact_id": artifact_id, "signature_type": signature_type, "uploaded": True}

        return await run_db(call)

    @mcp_tool(mcp, "upload_artifact_provenance", "sbom:manage", writes=True, idempotent=False)
    async def upload_artifact_provenance(principal: Principal, artifact_id: str, content: str) -> dict[str, Any]:
        """Attach an in-toto provenance attestation to an artifact.

        `content` is the attestation as a JSON string: a DSSE envelope or a
        plain in-toto Statement. One of its subjects must carry the artifact's
        sha256, which `get_artifact` reports. An artifact takes one
        provenance attestation; a second upload is refused.
        """
        raw = content.encode("utf-8")
        enforce_upload_size(raw, label="Provenance")

        def call() -> dict[str, Any]:
            from sbomify.apps.sboms import apis

            lookup_artifact(principal, artifact_id)
            _settle(apis.upload_provenance(_with_body(principal, raw), artifact_id), action="Provenance upload")
            return {"artifact_id": artifact_id, "uploaded": True}

        return await run_db(call)
