"""The audit log settings tab: the event list, its export, and the retention form."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.views import View
from django.views.decorators.cache import never_cache

from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.htmx import HtmxFragmentMixin, htmx_error_response, htmx_success_response
from sbomify.apps.teams.models import Workspace
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin

from . import services
from .apis import export_response
from .models import RETENTION_MAX_DAYS, RETENTION_MIN_DAYS
from .presentation import ACTION_FILTERS, describe


def _date(value: str | None, *, end: bool = False) -> datetime | None:
    """A ``YYYY-MM-DD`` from the date inputs, as the start of that day (or of the next, for ``until``)."""
    day = parse_date(value or "")
    if day is None:
        return None
    moment = datetime.combine(day, time.min, tzinfo=timezone.get_current_timezone())
    return moment + timedelta(days=1) if end else moment


def filters_from(request: HttpRequest) -> services.AuditFilters:
    params = request.GET
    outcome = params.get("outcome", "")
    return services.AuditFilters(
        action=params.get("action", "")[:100],
        actor=params.get("actor", "").strip()[:255],
        outcome=outcome if outcome in services.OUTCOMES else "",
        since=_date(params.get("since")),
        until=_date(params.get("until"), end=True),
        search=params.get("q", "").strip()[:255],
    )


def _query(request: HttpRequest, **extra: Any) -> str:
    keep = {k: request.GET[k] for k in ("action", "actor", "outcome", "since", "until", "q") if request.GET.get(k)}
    keep.update({k: v for k, v in extra.items() if v is not None})
    return urlencode(keep)


class _AuditView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = list(ADMINISTER)

    def workspace(self, workspace_key: str) -> Workspace | None:
        return Workspace.objects.filter(key=workspace_key).first()


@method_decorator(never_cache, name="dispatch")
class AuditLogView(HtmxFragmentMixin, _AuditView):
    def get(self, request: HttpRequest, workspace_key: str) -> HttpResponse:
        workspace = self.workspace(workspace_key)
        if workspace is None:
            return htmx_error_response("Workspace not found")

        allowed = services.authorize(request, workspace)
        if not allowed.ok:
            if allowed.status_code == 402:
                return render(request, "audit/upgrade.html.j2", {"workspace": workspace})
            return htmx_error_response(allowed.error or "Forbidden")

        filters = filters_from(request)
        cursor = request.GET.get("cursor")
        page = services.list_events(workspace.pk, filters, cursor=int(cursor) if cursor and cursor.isdigit() else None)
        url = reverse("audit:events", kwargs={"workspace_key": workspace.key})
        export_url = reverse("audit:export", kwargs={"workspace_key": workspace.key})
        context = {
            "workspace": workspace,
            "rows": [describe(event) for event in page.events],
            "more_url": f"{url}?{_query(request, cursor=page.next_cursor, rows=1)}" if page.next_cursor else "",
            "events_url": url,
            "export_csv_url": f"{export_url}?{_query(request, format='csv')}",
            "export_jsonl_url": f"{export_url}?{_query(request, format='jsonl')}",
            "params": request.GET,
            "action_filters": ACTION_FILTERS,
            "outcomes": services.OUTCOMES,
            "retention_days": workspace.audit_log_retention_days,
            "retention_min": RETENTION_MIN_DAYS,
            "retention_max": RETENTION_MAX_DAYS,
            "is_filtered": bool(filters.as_dict()),
        }
        template = "audit/rows.html.j2" if request.GET.get("rows") else "audit/events.html.j2"
        return render(request, template, context)


@method_decorator(never_cache, name="dispatch")
class AuditLogExportView(_AuditView):
    def get(self, request: HttpRequest, workspace_key: str) -> HttpResponseBase:
        workspace = self.workspace(workspace_key)
        if workspace is None:
            return HttpResponse("Workspace not found", status=404)
        allowed = services.authorize(request, workspace)
        if not allowed.ok:
            return HttpResponse(allowed.error, status=allowed.status_code or 403)
        export_format = "jsonl" if request.GET.get("format") == "jsonl" else "csv"
        return export_response(workspace, filters_from(request), export_format)


class AuditRetentionView(_AuditView):
    def post(self, request: HttpRequest, workspace_key: str) -> HttpResponse:
        workspace = self.workspace(workspace_key)
        if workspace is None:
            return htmx_error_response("Workspace not found")
        try:
            days = int(request.POST.get("retention_days", ""))
        except ValueError:
            return htmx_error_response(f"Enter a number of days from {RETENTION_MIN_DAYS} to {RETENTION_MAX_DAYS}.")
        result = services.update_retention(request, workspace, days)
        if not result.ok:
            return htmx_error_response(result.error or "Could not save the retention period.")
        return htmx_success_response(f"Audit events are now kept for {days} days.")
