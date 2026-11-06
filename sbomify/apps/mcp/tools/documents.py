"""Document upload and editing tools.

Both delegate to the REST views, which own the duplicate guard, the object
store write and the workspace broadcast. The file is stored byte for byte as
supplied (ADR-004).
"""

from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import serializers
from ..auth import Principal
from ..limits import MAX_UPLOAD_BYTES
from ._base import mcp_tool, not_found, resolve_workspace, run_db, unwrap_view
from .catalog import _lookup_component
from .publish import _with_body

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def decode_base64(content_base64: str, *, label: str) -> bytes:
    """Decode an agent-supplied base64 file, refusing an oversized one before decoding it."""
    text = "".join(content_base64.split())
    size = len(text) * 3 // 4 - text[-2:].count("=")
    if size > MAX_UPLOAD_BYTES:
        raise ToolError(
            f"{label} is {size} bytes, over the {MAX_UPLOAD_BYTES} byte limit for MCP uploads. "
            "Use the REST API or the web uploader for files this large."
        )
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ToolError(f"{label} is not valid base64: {exc}") from exc
    if not raw:
        raise ToolError(f"{label} is empty.")
    return raw


def _check_document_type(document_type: str | None) -> None:
    from sbomify.apps.documents.models import Document

    if document_type and document_type not in set(Document.DocumentType.values):
        raise ToolError(
            f"Unknown document_type {document_type!r}; "
            f"expected one of {', '.join(sorted(Document.DocumentType.values))}."
        )


def register_tools(mcp: FastMCP) -> None:
    @mcp_tool(mcp, "create_document", "artifact:publish", writes=True, idempotent=False)
    async def create_document(
        principal: Principal,
        component_id: str,
        name: str,
        content_base64: str,
        version: str = "1.0",
        document_type: str = "",
        description: str = "",
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Upload a document (a PDF, a policy, release notes) to a document component.

        `content_base64` is the whole file, base64-encoded; it is stored exactly
        as decoded. `content_type` is its media type, such as application/pdf.
        `document_type` is one of the document kinds sbomify knows, such as
        security-advisory, release-notes or license; leave it empty if none fits.
        The component must be a document component. A document with the same
        name and version already on the component is refused as a duplicate.
        Returns the new document's id.
        """
        _check_document_type(document_type)

        def call() -> dict[str, Any]:
            from sbomify.apps.documents.apis import create_document as view

            # Decoded here, on the worker thread: a file up to the upload limit
            # decoded on the event loop would stall every other request it serves.
            raw = decode_base64(content_base64, label="Document")
            _lookup_component(principal, component_id)
            request = _with_body(principal, raw)
            request.content_type = content_type
            return unwrap_view(
                view(
                    request,
                    component_id=component_id,
                    document_file=None,  # type: ignore[arg-type]  # the view's File(None) default, read as "no file"
                    name=name,
                    version=version,
                    document_type=document_type,
                    description=description,
                ),
                action="Document upload",
            )

        return await run_db(call)

    @mcp_tool(mcp, "update_document", "document:manage", writes=True, idempotent=True)
    async def update_document(
        principal: Principal,
        document_id: str,
        name: str | None = None,
        version: str | None = None,
        document_type: str | None = None,
        compliance_subcategory: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Change a document's name, version, type or description. The file itself is not changed.

        Pass only the fields to change. `compliance_subcategory` applies to
        compliance documents only. Renaming onto a name and version the
        component already holds is refused as a duplicate.
        """
        _check_document_type(document_type)

        def call() -> dict[str, Any]:
            from sbomify.apps.documents.apis import update_document as view
            from sbomify.apps.documents.models import Document
            from sbomify.apps.documents.schemas import DocumentUpdateRequest

            team = resolve_workspace(principal)
            if not Document.objects.filter(pk=document_id, component__team=team).exists():
                raise not_found("Document", document_id)
            fields = {
                key: value
                for key, value in {
                    "name": name,
                    "version": version,
                    "document_type": document_type,
                    "compliance_subcategory": compliance_subcategory,
                    "description": description,
                }.items()
                if value is not None
            }
            if not fields:
                raise ToolError("Nothing to update: pass at least one field.")
            updated = unwrap_view(
                view(principal.request, document_id, DocumentUpdateRequest(**fields)), action="Document update"
            )
            return serializers.compact(
                {
                    key: updated.get(key)
                    for key in ("id", "name", "version", "document_type", "compliance_subcategory", "description")
                }
            )

        return await run_db(call)
