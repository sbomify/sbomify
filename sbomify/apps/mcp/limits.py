"""Resource limits and audit logging for MCP tool calls.

The MCP endpoint is a higher-risk surface than the REST API for one specific
reason: the caller is an LLM, and an LLM's inputs are frequently attacker-
influenced. A package name inside an uploaded SBOM, a product description, or a
document's text can all carry instructions aimed at the agent reading them. The
agent is authenticated as a real user, so a successful injection borrows that
user's authority.

The defences layer as follows, strongest first:

1. **Token scopes** (``core.authz.can``) — a prompt cannot widen what the token
   may do. This is the real boundary; everything below is depth.
2. **No destructive tools.** ``*:delete`` actions are deliberately never
   registered, so "delete all our SBOMs" has no tool to reach for.
3. **Resource caps** (this module) — a coerced agent cannot exhaust memory or
   storage.
4. **Audit trail** (this module) — every call is attributable to a token,
   workspace and user, so abuse is reconstructable after the fact.
5. **Provenance marking** (``untrusted``) — artifact-derived text is labelled so
   the model treats it as data rather than instructions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.conf import settings
from mcp.server.fastmcp.exceptions import ToolError

from sbomify.logging import getLogger

if TYPE_CHECKING:
    from .auth import Principal

# sbomify.logging.getLogger prepends "sbomify.", yielding "sbomify.audit.mcp" —
# under the "sbomify.audit" logger that settings pins to INFO independent of
# LOG_LEVEL. Passing the full name here would double the prefix and drop
# success events whenever LOG_LEVEL is raised.
log = getLogger("audit.mcp")

# Defined unconditionally in settings.py, so no fallback defaults here — a
# second copy of each default would drift from the one settings actually uses.
MAX_UPLOAD_BYTES: int = settings.MCP_MAX_UPLOAD_BYTES
"""Largest artifact an MCP tool will accept. Defaults to Django's
``DATA_UPLOAD_MAX_MEMORY_SIZE`` so MCP is never the laxer of the two doors."""

MAX_ARTIFACT_PARSE_BYTES: int = settings.MCP_MAX_ARTIFACT_PARSE_BYTES
"""Largest stored artifact ``get_sbom_packages`` will pull into memory to parse.
Higher than the upload cap because artifacts predating this limit — or uploaded
through other paths — can legitimately be larger; the point is to fail with a
clear message instead of an OOM that takes the worker down."""

MAX_RESPONSE_BYTES: int = settings.MCP_MAX_RESPONSE_BYTES
"""Ceiling on a single tool's serialized response. Pagination should keep every
response far below this; tripping it means a tool has an unbounded field."""


def enforce_upload_size(raw: bytes, *, label: str) -> None:
    """Reject an oversized upload before it reaches storage."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ToolError(
            f"{label} is {len(raw) // 1024 // 1024} MB, over the "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB limit for MCP uploads. "
            "Use the REST API or the web uploader for artifacts this large."
        )


def enforce_parse_size(raw: bytes | None, *, sbom_id: str) -> None:
    """Refuse to parse a stored artifact that would not fit comfortably in memory."""
    if raw is not None and len(raw) > MAX_ARTIFACT_PARSE_BYTES:
        raise ToolError(
            f"SBOM {sbom_id} is {len(raw) // 1024 // 1024} MB, too large to inspect over MCP. "
            "Download it directly instead."
        )


def enforce_response_size(payload: Any, *, tool: str) -> Any:
    """Guard against a tool returning an unbounded response.

    A backstop, not the primary control: tools paginate, so reaching this means
    a field grew without a cap and the agent's context would have been flooded.
    """
    size = len(json.dumps(payload, default=str).encode("utf-8"))
    if size > MAX_RESPONSE_BYTES:
        raise ToolError(
            f"{tool} produced a {size // 1024} KB response, over the "
            f"{MAX_RESPONSE_BYTES // 1024} KB limit. Narrow the query "
            "(filter, or a smaller page_size)."
        )
    return payload


def audit(
    tool: str,
    principal: Principal,
    *,
    outcome: str,
    detail: str | None = None,
    **fields: Any,
) -> None:
    """Emit one structured audit event for an MCP tool call.

    Mirrors the token-auth audit events in ``access_tokens.utils``: never logs
    artifact content or the raw token, only identifiers. ``arguments`` are
    deliberately not logged — they can contain a whole SBOM.
    """
    event = {
        "outcome": outcome,
        "tool": tool,
        "token_id": str(principal.token.pk),
        "user_id": str(principal.user.pk),
        "team_id": str(principal.token.team_id) if principal.token.team_id is not None else None,
        "scoped": principal.scopes is not None,
        "detail": detail,
        **fields,
    }
    message = f"mcp_tool_call {json.dumps(event, default=str)}"
    if outcome == "success":
        log.info(message, extra={"event": "mcp_tool_call", **event})
    else:
        log.warning(message, extra={"event": "mcp_tool_call", **event})


def untrusted(value: str | None, *, limit: int = 4000) -> str | None:
    """Truncate free text that originated outside sbomify.

    Names and descriptions inside uploaded artifacts are attacker-controlled.
    Truncation bounds how much of an injected payload can reach the model in one
    field; the accompanying warning in the server instructions is what tells the
    model to treat these values as data.
    """
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return f"{value[:limit]}… [truncated by sbomify]"
