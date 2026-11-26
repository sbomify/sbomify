"""Who is acting, and from where, for the duration of one request or tool call.

The middleware opens a context for every HTTP request and the MCP tool wrapper
opens one for every tool call. Anything recorded while it is open (a model
change picked up by a signal, a sign-in, an explicit ``record``) is attributed
to that actor. Model changes made with no context open (a background task, a
migration, a management command) are not user activity and are not recorded.

A ``ContextVar`` rather than a thread local, so the MCP tool wrapper's context
follows the call into the executor thread ``run_db`` hands ORM work to.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from django.http import HttpRequest


@dataclass
class AuditContext:
    request: HttpRequest | None = None
    #: Set when the actor is not ``request.user`` (the MCP principal, or a
    #: sign-in recorded before the session switched users).
    user: Any = None
    channel: str | None = None
    actor_type: str | None = None
    credential_kind: str = ""
    credential_id: str = ""
    workspace_id: int | None = None
    ip_address: str | None = None
    user_agent: str = ""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    http_method: str = ""
    path: str = ""
    #: How many events this context has recorded. The middleware records a
    #: generic request event only when nothing more specific was.
    recorded: int = 0
    #: Per-context caches: workspace id -> audit log enabled, and
    #: (user id, workspace id) -> role.
    entitled: dict[int, bool] = field(default_factory=dict)
    roles: dict[tuple[int, int], str] = field(default_factory=dict)


_current: ContextVar[AuditContext | None] = ContextVar("sbomify_audit_context", default=None)


def current() -> AuditContext | None:
    return _current.get()


def enter(ctx: AuditContext) -> Token[AuditContext | None]:
    return _current.set(ctx)


def leave(token: Token[AuditContext | None]) -> None:
    _current.reset(token)


@contextmanager
def audit_context(ctx: AuditContext) -> Iterator[AuditContext]:
    token = enter(ctx)
    try:
        yield ctx
    finally:
        leave(token)


def from_request(request: HttpRequest) -> AuditContext:
    from sbomify.apps.core.utils import get_client_ip

    return AuditContext(
        request=request,
        ip_address=get_client_ip(request),
        user_agent=(request.headers.get("User-Agent") or "")[:512],
        http_method=request.method or "",
        path=request.path[:512],
    )
