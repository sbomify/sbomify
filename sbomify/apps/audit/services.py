"""Reading, exporting and expiring the audit log.

Access is decided by ``authorize`` and nowhere else: the web tab, the CSV
download and the API all go through it, so "who may read the audit log" has one
answer. It is the ``audit_log:read`` action, which is ``ADMINISTER`` (owners and
admins), on a workspace whose plan includes the audit log.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from itertools import islice
from typing import Any

from asgiref.sync import sync_to_async
from defusedcsv import csv
from django.db import connection
from django.db.models import Q, QuerySet
from django.http import HttpRequest

from sbomify.apps.core.authz import can
from sbomify.apps.core.services.results import ServiceResult

from .models import RETENTION_DEFAULT_DAYS, RETENTION_MAX_DAYS, RETENTION_MIN_DAYS, AuditEvent, Outcome
from .recorder import Target, plan_has_audit_log, record

PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
# One export is bounded so a single download cannot hold a worker for minutes;
# narrow the date range to fetch more.
MAX_EXPORT_ROWS = 100_000

EXPORT_COLUMNS: tuple[str, ...] = (
    "event_id",
    "occurred_at",
    "action",
    "outcome",
    "actor_type",
    "actor_user_id",
    "actor_label",
    "actor_role",
    "channel",
    "credential_kind",
    "credential_id",
    "target_type",
    "target_id",
    "target_label",
    "ip_address",
    "user_agent",
    "request_id",
    "http_method",
    "path",
    "status_code",
    "metadata",
    "chain_seq",
    "prev_hash",
    "entry_hash",
)


@dataclass(frozen=True)
class AuditFilters:
    action: str = ""
    actor: str = ""
    target_type: str = ""
    target_id: str = ""
    outcome: str = ""
    since: datetime | None = None
    until: datetime | None = None
    search: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in self.__dict__.items() if v}


@dataclass(frozen=True)
class AuditPage:
    events: list[AuditEvent]
    next_cursor: int | None
    filters: AuditFilters = field(default_factory=AuditFilters)


def authorize(request: HttpRequest, workspace: Any, action: str = "audit_log:read") -> ServiceResult[None]:
    if not plan_has_audit_log(workspace.billing_plan):
        return ServiceResult.failure("The audit log is available on the Enterprise plan.", status_code=402)
    if not can(request, action, workspace):
        if action == "audit_log:manage":
            return ServiceResult.failure("Only the workspace owner can change audit log retention.", status_code=403)
        return ServiceResult.failure("Only workspace owners and admins can view the audit log.", status_code=403)
    return ServiceResult.success()


def _filtered(workspace_id: int, filters: AuditFilters) -> QuerySet[AuditEvent]:
    queryset = AuditEvent.objects.filter(workspace_id=workspace_id)
    if filters.action:
        # "product" or "product." matches every product action; anything with a
        # verb matches exactly.
        prefix = filters.action.rstrip(".")
        queryset = queryset.filter(Q(action=prefix) | Q(action__startswith=f"{prefix}."))
    if filters.actor:
        if filters.actor.isdigit():
            queryset = queryset.filter(actor_user_id=int(filters.actor))
        else:
            queryset = queryset.filter(actor_label__icontains=filters.actor)
    if filters.target_type:
        queryset = queryset.filter(target_type=filters.target_type)
    if filters.target_id:
        queryset = queryset.filter(target_id=filters.target_id)
    if filters.outcome:
        queryset = queryset.filter(outcome=filters.outcome)
    if filters.since:
        queryset = queryset.filter(occurred_at__gte=filters.since)
    if filters.until:
        queryset = queryset.filter(occurred_at__lt=filters.until)
    if filters.search:
        queryset = queryset.filter(
            Q(target_label__icontains=filters.search)
            | Q(actor_label__icontains=filters.search)
            | Q(action__icontains=filters.search)
        )
    return queryset.order_by("-id")


def list_events(
    workspace_id: int, filters: AuditFilters, *, cursor: int | None = None, limit: int = PAGE_SIZE
) -> AuditPage:
    """One page, newest first. ``cursor`` is the id the previous page ended at."""
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    queryset = _filtered(workspace_id, filters)
    if cursor is not None:
        queryset = queryset.filter(id__lt=cursor)
    rows = list(queryset[: limit + 1])
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return AuditPage(events=rows[:limit], next_cursor=next_cursor, filters=filters)


def serialize(event: AuditEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "occurred_at": event.occurred_at.isoformat(),
        "action": event.action,
        "outcome": event.outcome,
        "actor": {
            "type": event.actor_type,
            "user_id": event.actor_user_id,
            "label": event.actor_label,
            "role": event.actor_role,
        },
        "channel": event.channel,
        "credential": {"kind": event.credential_kind, "id": event.credential_id},
        "target": {"type": event.target_type, "id": event.target_id, "label": event.target_label},
        "request": {
            "id": event.request_id,
            "ip_address": event.ip_address,
            "user_agent": event.user_agent,
            "method": event.http_method,
            "path": event.path,
            "status_code": event.status_code,
        },
        "metadata": event.metadata,
        "chain": {"seq": event.chain_seq, "prev_hash": event.prev_hash, "entry_hash": event.entry_hash},
    }


def _row(event: AuditEvent) -> list[Any]:
    values = []
    for column in EXPORT_COLUMNS:
        value = getattr(event, column)
        if column == "metadata":
            value = json.dumps(value, sort_keys=True, default=str)
        elif column == "occurred_at":
            value = value.isoformat()
        values.append("" if value is None else value)
    return values


def _export_queryset(workspace_id: int, filters: AuditFilters) -> Iterator[AuditEvent]:
    return _filtered(workspace_id, filters)[:MAX_EXPORT_ROWS].iterator(chunk_size=2000)


def export_csv(workspace_id: int, filters: AuditFilters) -> Iterator[str]:
    """CSV, header first, streamed a row at a time."""
    buffer = io.StringIO()
    # This is defusedcsv's writer (see the import), which neutralises formula
    # injection; the rule matches on the name alone.
    writer = csv.writer(buffer)  # type: ignore[no-untyped-call]  # nosemgrep: opengrep-rules.python.lang.security.use-defusedcsv

    def flush() -> str:
        value = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return value

    writer.writerow(EXPORT_COLUMNS)
    yield flush()
    for event in _export_queryset(workspace_id, filters):
        writer.writerow(_row(event))
        yield flush()


def export_jsonl(workspace_id: int, filters: AuditFilters) -> Iterator[str]:
    """One JSON object per line, the shape SIEM collectors ingest."""
    for event in _export_queryset(workspace_id, filters):
        yield json.dumps(serialize(event), default=str) + "\n"


EXPORT_BATCH = 500


async def batched_async(lines: Iterator[str]) -> AsyncIterator[str]:
    """Yield ``lines`` from an async context, a few hundred at a time.

    Each batch is pulled on the database thread. thread_sensitive keeps every
    pull on the same thread, which the server-side cursor behind the iterator
    needs.
    """

    def take() -> str:
        return "".join(islice(lines, EXPORT_BATCH))

    while chunk := await sync_to_async(take, thread_sensitive=True)():
        yield chunk


def record_export(workspace: Any, filters: AuditFilters, export_format: str) -> None:
    """Reading the log in bulk is itself an event an auditor will ask about."""
    record(
        "audit_log.exported",
        workspace=workspace,
        target=Target("audit_log", str(workspace.pk), "Audit log"),
        metadata={"format": export_format, "filters": filters.as_dict()},
    )


def update_retention(request: HttpRequest, workspace: Any, days: int) -> ServiceResult[int]:
    allowed = authorize(request, workspace, "audit_log:manage")
    if not allowed.ok:
        return ServiceResult.failure(allowed.error or "Forbidden", status_code=allowed.status_code)
    if not RETENTION_MIN_DAYS <= days <= RETENTION_MAX_DAYS:
        return ServiceResult.failure(
            f"Keep events for between {RETENTION_MIN_DAYS} and {RETENTION_MAX_DAYS} days.", status_code=400
        )
    workspace.audit_log_retention_days = days
    # A tracked field: the change is recorded as workspace.updated.
    workspace.save(update_fields=["audit_log_retention_days"])
    return ServiceResult.success(days)


def record_retention_refused(workspace: Any, days: int) -> None:
    """A refused retention change is recorded like an applied one, as denied.

    The HTMX form answers a refusal with a 200 toast, so the request event the
    middleware writes would read as a success. The API answers 403 and the
    middleware records that one.
    """
    record(
        "workspace.updated",
        workspace=workspace,
        target=Target("workspace", str(workspace.pk), str(workspace.name or "")),
        outcome=Outcome.DENIED,
        metadata={"changes": {"audit_log_retention_days": {"from": workspace.audit_log_retention_days, "to": days}}},
    )


PURGE_BATCH = 5000

# Literal, parameterised statements: the table names are fixed and every
# value is bound by the driver.
#
# One workspace at a time, so each delete walks the (workspace_id, occurred_at)
# index rather than joining every event to its workspace. The chain heads hold
# one row per workspace that has ever recorded an event, deleted workspaces
# included, which is the list to walk.
PURGE_WORKSPACES_SQL = """
SELECT h.workspace_id, GREATEST(COALESCE(w.audit_log_retention_days, %s), %s)
  FROM audit_chain_heads h
  LEFT JOIN workspaces_workspaces w ON w.id = h.workspace_id
 WHERE h.purged_through_seq < h.last_seq
"""

PURGE_SQL = """
DELETE FROM audit_events
 WHERE id IN (
   SELECT id
     FROM audit_events
    WHERE workspace_id = %s
      AND occurred_at < now() - make_interval(days => %s)
    ORDER BY occurred_at
    LIMIT %s
 )
"""


def purge_expired() -> int:
    """Delete every event past its workspace's retention window. Returns the count.

    The window is the same one the delete trigger enforces, so this never asks
    for a row the database would refuse. Batched to keep each transaction, and
    the locks it holds, short.
    """
    with connection.cursor() as cursor:
        cursor.execute(PURGE_WORKSPACES_SQL, [RETENTION_DEFAULT_DAYS, RETENTION_MIN_DAYS])
        workspaces = cursor.fetchall()

    total = 0
    for workspace_id, retention_days in workspaces:
        while True:
            with connection.cursor() as cursor:
                cursor.execute(PURGE_SQL, [workspace_id, retention_days, PURGE_BATCH])
                deleted = int(cursor.rowcount)
            total += deleted
            if deleted < PURGE_BATCH:
                break
    return total


OUTCOMES = [value for value, _label in Outcome.choices]
