"""Audit context and events for MCP tool calls.

``/mcp`` is served before Django's request handling, so the middleware never
sees it. The tool wrapper opens this context instead: every change a tool makes
is attributed to the agent and the person it acts for, and every call, read or
write, allowed or refused, is one ``agent.tool_call`` event.
"""

from __future__ import annotations

import logging
from typing import Any

from .context import AuditContext
from .models import ActorType, Channel
from .recorder import Target, record

logger = logging.getLogger(__name__)


def context_for(principal: Any) -> AuditContext:
    from sbomify.apps.core.utils import get_client_ip

    is_ci = principal.credential_kind == "oidc"
    stub = principal.request
    return AuditContext(
        user=principal.user,
        channel=Channel.CI if is_ci else Channel.MCP,
        actor_type=ActorType.BOT if is_ci else ActorType.AGENT,
        credential_kind=principal.credential_kind,
        credential_id=str(principal.credential_id),
        ip_address=get_client_ip(stub),
        http_method="POST",
        path=str(getattr(stub, "path", "") or "/mcp")[:512],
    )


def record_tool_call(principal: Any, tool: str, *, outcome: str, writes: bool) -> None:
    """Record one tool call. Never raises: it runs on the way out of a refusal too."""
    workspace = principal.resolved_workspace or principal.workspace
    if workspace is None:
        return
    try:
        _record(principal, tool, workspace, outcome=outcome, writes=writes)
    except Exception:
        logger.exception("audit_tool_call_failed tool=%s", tool)


def _record(principal: Any, tool: str, workspace: Any, *, outcome: str, writes: bool) -> None:
    record(
        "agent.tool_call",
        workspace=workspace,
        target=Target("tool", tool, tool),
        outcome=outcome,
        metadata={"tool": tool, "writes": writes},
    )
