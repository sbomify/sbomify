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
"""Largest stored artifact ``get_artifact_packages`` will pull into memory to parse.
Higher than the upload cap because artifacts predating this limit — or uploaded
through other paths — can legitimately be larger; the point is to fail with a
clear message instead of an OOM that takes the worker down."""

MAX_RESPONSE_BYTES: int = settings.MCP_MAX_RESPONSE_BYTES
"""Ceiling on a single tool's serialized response. Pagination should keep every
response far below this; tripping it means a tool has an unbounded field."""

DETAIL_COLLECTION_LIMIT = 50
"""How many rows a detail tool returns from one of its folded-in collections.

A detail tool answers with several collections at once and so takes no page
arguments. Left unbounded, a large enough product tripped the response cap and
the agent was told to narrow a query it had no argument to narrow with. Fifty
is enough to answer "what is in this" for almost everything and small enough
that the several collections together stay well inside the cap."""


def enforce_upload_size(raw: bytes, *, label: str) -> None:
    """Reject an oversized upload before it reaches storage.

    Sizes are reported in bytes rather than MB because both figures used to be
    integer-truncated: a 21,000,000 byte upload against a 20 MB limit read "is
    20 MB, over the 20 MB limit", and an agent told the size it sent is not over
    the limit retries it unchanged.
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ToolError(
            f"{label} is {len(raw)} bytes, over the {MAX_UPLOAD_BYTES} byte limit for MCP uploads. "
            "Use the REST API or the web uploader for artifacts this large."
        )


PARSE_MEMORY_FACTOR = 8
"""How many times the byte ceiling a document may take once parsed.

Real SBOMs take two to four times their size as Python objects, so one at the
ceiling fits. A document built of tiny objects takes up to thirty times, and
that is what this refuses."""


def parsed_size_estimate(raw: bytes) -> int:
    """An upper bound on what ``json.loads(raw)`` holds in memory, read from the text alone.

    Each object or array costs up to about 256 bytes once parsed, each further
    member about 64, and text about twice its length. Measured against the SBOM
    fixtures and against arrays of empty objects, arrays, zeros and strings,
    every one came in under it. A brace or comma inside a string only makes it
    higher. Three byte counts, so a document is sized without being parsed.
    """
    containers = raw.count(b"{") + raw.count(b"[")
    return 2 * len(raw) + 256 * containers + 64 * raw.count(b",")


def within_parse_budget(raw: bytes, ceiling: int) -> bool:
    """Whether ``raw`` is under ``ceiling`` bytes and parses into no more than ``PARSE_MEMORY_FACTOR`` times it."""
    return len(raw) <= ceiling and parsed_size_estimate(raw) <= PARSE_MEMORY_FACTOR * ceiling


def enforce_parse_size(raw: bytes | None, *, artifact_id: str) -> None:
    """Refuse to parse a stored artifact that would not fit comfortably in memory.

    The byte ceiling alone does not bound memory: ``json.loads`` builds an object
    per value, and a document of small enough values grows many times over.
    """
    if raw is None:
        return
    enforce_stored_size(len(raw), artifact_id=artifact_id)
    if not within_parse_budget(raw, MAX_ARTIFACT_PARSE_BYTES):
        raise ToolError(
            f"Artifact {artifact_id} is built of too many small parts to read over MCP: parsed, it would "
            f"take more than {PARSE_MEMORY_FACTOR * MAX_ARTIFACT_PARSE_BYTES} bytes. Download it directly instead."
        )


def enforce_stored_size(size: int | None, *, artifact_id: str) -> None:
    """The same ceiling, from a size known before the bytes are in hand.

    Checking only after the download made the cap advisory: an oversized
    artifact still cost its full transfer and its full place in memory before
    anything refused it, which is the outcome the cap exists to prevent. A HEAD
    against the store answers this for the price of one round trip.

    ``None`` means the store has no such object, which is the caller's
    not-found to raise rather than an over-size refusal.
    """
    if size is not None and size > MAX_ARTIFACT_PARSE_BYTES:
        raise ToolError(
            f"Artifact {artifact_id} is {size} bytes, over the {MAX_ARTIFACT_PARSE_BYTES} byte "
            "limit for inspection over MCP. Download it directly instead."
        )


def enforce_response_size(payload: Any, *, tool: str, wrote: bool = False) -> Any:
    """Guard against a tool returning an unbounded response.

    A backstop, not the primary control: tools paginate, so reaching this means
    a field grew without a cap and the agent's context would have been flooded.

    A tool that ``wrote`` has already saved its change, so it answers with a
    short receipt instead: an error now would read as a failure, and a retry
    would make the change a second time.
    """
    size = len(json.dumps(payload, default=str).encode("utf-8"))
    if size > MAX_RESPONSE_BYTES:
        if wrote:
            return written_receipt(payload)
        raise ToolError(
            f"{tool} produced a {size // 1024} KB response, over the "
            f"{MAX_RESPONSE_BYTES // 1024} KB limit. Narrow the query "
            "(filter, or a smaller page_size)."
        )
    return payload


RECEIPT_TEXT_LIMIT = 256


def written_receipt(payload: Any) -> dict[str, Any]:
    """The fields that identify a write's result, each short, for an answer over the cap.

    Text is cut, a list becomes its count, and nested objects are left out, so
    the receipt's size depends only on how many fields the tool returns.
    """
    receipt: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, str):
                receipt[key] = untrusted(value, limit=RECEIPT_TEXT_LIMIT)
            elif isinstance(value, list | tuple):
                # A total the tool reported for a list it cut is the true one.
                receipt.setdefault(f"{key}_total", len(value))
            elif value is None or isinstance(value, bool | int | float):
                receipt[key] = value
    receipt["response_truncated"] = True
    receipt["note"] = "The change was saved. Its answer was over the size limit: read it with the get or list tool."
    return receipt


def _team_id(principal: Principal) -> str | None:
    if (team := principal.resolved_workspace) is not None:
        return str(team.pk)
    return str(principal.token.team_id) if principal.token.team_id is not None else None


def audit(
    tool: str,
    principal: Principal | None,
    *,
    outcome: str,
    detail: str | None = None,
    **fields: Any,
) -> None:
    """Emit one structured audit event for an MCP tool call.

    Mirrors the token-auth audit events in ``access_tokens.utils``: never logs
    artifact content or the raw token, only identifiers. ``arguments`` are
    deliberately not logged — they can contain a whole SBOM.

    ``principal`` is None for a request refused before any credential resolved.
    """
    event = {
        "outcome": outcome,
        "tool": tool,
        "token_id": str(principal.token.pk) if principal else None,
        "user_id": str(principal.user.pk) if principal else None,
        # The workspace the call operated in, not the one the token names.
        # ``AccessToken.team`` is nullable, and such a token falls back to the
        # user's default in ``resolve_workspace`` — so recording the token's own
        # field logged null for a legacy token's every read and write, which is
        # the opposite of "abuse is reconstructable after the fact". Falls back
        # to the token's field for the refusals that happen before any tool body
        # runs, where nothing has been resolved yet.
        "team_id": _team_id(principal) if principal else None,
        "scoped": principal.scopes is not None if principal else None,
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
