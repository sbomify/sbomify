"""Writing audit events.

``record`` is the one way in. It resolves the actor from the open
``AuditContext``, drops the event if the workspace is not on a plan with the
audit log, and writes it once the surrounding transaction commits, so the trail
never claims a change that rolled back. Refusals and failures are written
straight away instead: there is often no commit for them to wait on.

A failure to write is logged and swallowed. The change it describes has already
been committed by then, and failing the request would not undo it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from .context import AuditContext, current
from .models import ActorType, AuditEvent, Channel, Outcome

logger = logging.getLogger(__name__)

AUDIT_PLAN_KEYS: frozenset[str] = frozenset({"enterprise"})


@dataclass(frozen=True)
class Target:
    type: str
    id: str = ""
    label: str = ""


def plan_has_audit_log(billing_plan: str | None) -> bool:
    from sbomify.apps.billing.config import is_billing_enabled

    # A self-hosted deployment runs without billing and has every feature.
    if not is_billing_enabled():
        return True
    return (billing_plan or "").strip().lower() in AUDIT_PLAN_KEYS


def workspace_has_audit_log(workspace_id: int | None, ctx: AuditContext | None = None) -> bool:
    if workspace_id is None:
        return False
    if ctx is not None and workspace_id in ctx.entitled:
        return ctx.entitled[workspace_id]

    from sbomify.apps.teams.models import Workspace

    plans = list(Workspace.objects.filter(pk=workspace_id).values_list("billing_plan", flat=True))
    enabled = bool(plans) and plan_has_audit_log(plans[0])
    if ctx is not None:
        ctx.entitled[workspace_id] = enabled
    return enabled


def _workspace_id(workspace: Any) -> int | None:
    if workspace is None:
        return None
    if isinstance(workspace, int | str):
        # A foreign key assigned from a string id stays a string on the instance.
        try:
            return int(workspace)
        except ValueError:
            return None
    return getattr(workspace, "pk", None)


def _role(user_id: int, workspace_id: int, ctx: AuditContext | None) -> str:
    key = (user_id, workspace_id)
    if ctx is not None and key in ctx.roles:
        return ctx.roles[key]
    from sbomify.apps.teams.models import Member

    role = Member.objects.filter(user_id=user_id, team_id=workspace_id).values_list("role", flat=True).first() or ""
    if ctx is not None:
        ctx.roles[key] = role
    return role


def _actor(ctx: AuditContext | None, override: Any) -> dict[str, Any]:
    """The actor columns, from an explicit user or the open context."""
    from sbomify.apps.core.authz import credential_channel

    request = ctx.request if ctx is not None else None
    user = override if override is not None else (ctx.user if ctx is not None else None)
    if user is None and request is not None:
        user = getattr(request, "user", None)
    if user is not None and not getattr(user, "is_authenticated", False):
        user = None

    channel = ctx.channel if ctx is not None else None
    actor_type = ctx.actor_type if ctx is not None else None
    credential_kind = ctx.credential_kind if ctx is not None else ""
    credential_id = ctx.credential_id if ctx is not None else ""

    token = getattr(request, "access_token_record", None) if request is not None else None
    if request is not None and channel is None:
        if token is not None:
            via = credential_channel(request)
            channel = Channel.CI if via == "ci" else Channel.API
            actor_type = ActorType.BOT if via == "ci" else ActorType.AGENT if via == "agent" else ActorType.USER
            credential_kind = "oidc" if via == "ci" else "pat"
            credential_id = str(token.pk)
        else:
            channel = Channel.API if request.path.startswith("/api/") else Channel.WEB
            credential_kind = "session" if user is not None else ""

    return {
        "user": user,
        "actor_user_id": getattr(user, "pk", None),
        "actor_label": ((getattr(user, "email", "") or getattr(user, "username", "")) if user else "")[:255],
        "actor_type": actor_type or ActorType.USER,
        "channel": channel or Channel.WEB,
        "credential_kind": credential_kind,
        "credential_id": credential_id[:64],
    }


def snapshot_actor_role(workspace_id: int) -> None:
    """Remember the actor's role before membership changes or cascades."""
    ctx = current()
    if ctx is not None:
        user = _actor(ctx, None)["user"]
        if user is not None:
            _role(user.pk, workspace_id, ctx)


def record(
    action: str,
    *,
    workspace: Any,
    target: Target | None = None,
    outcome: str = Outcome.SUCCESS,
    metadata: dict[str, Any] | None = None,
    actor: Any = None,
    status_code: int | None = None,
    require_actor: bool = True,
) -> bool:
    """Record ``action`` in ``workspace``'s audit log. True if it was queued.

    ``actor`` names the user when the context cannot (a sign-in, before the
    session holds them). With ``require_actor`` an event with no identifiable
    person behind it is dropped: the log is a record of what people and their
    agents did.
    """
    ctx = current()
    workspace_id = _workspace_id(workspace)
    if workspace_id is None or not workspace_has_audit_log(workspace_id, ctx):
        return False

    actor_fields = _actor(ctx, actor)
    user = actor_fields.pop("user")
    if require_actor and user is None:
        return False

    if ctx is not None:
        ctx.recorded += 1

    fields: dict[str, Any] = {
        "workspace_id": workspace_id,
        "action": action[:100],
        "outcome": outcome,
        **actor_fields,
        "actor_role": _role(user.pk, workspace_id, ctx)[:32] if user is not None else "",
        "target_type": (target.type if target else "")[:64],
        "target_id": (str(target.id) if target else "")[:64],
        "target_label": (target.label if target else "")[:255],
        "metadata": metadata or {},
        "status_code": status_code,
    }
    if ctx is not None:
        fields.update(
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            request_id=ctx.request_id,
            http_method=ctx.http_method,
            path=ctx.path,
        )

    if outcome == Outcome.SUCCESS:
        transaction.on_commit(lambda: _write(fields))
    else:
        _write(fields)
    return True


def _write(fields: dict[str, Any]) -> None:
    try:
        # Its own savepoint, so a failed insert inside an outer transaction
        # cannot poison it.
        with transaction.atomic():
            AuditEvent.objects.create(**fields)
    except Exception:
        logger.exception("audit_event_write_failed action=%s workspace=%s", fields["action"], fields["workspace_id"])
