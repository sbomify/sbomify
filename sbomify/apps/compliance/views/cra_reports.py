"""CRA Article 14 reports: the list, starting one, and the report page.

Readable by every internal role so operators see the deadlines; written by
owners and admins, who file. Not plan-gated: Article 14 binds every
manufacturer.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from sbomify.apps.compliance.forms import CRAFilingForm, CRAReportCreateForm, CRAReportForm
from sbomify.apps.compliance.reporting import DEADLINE_STAGES, STAGE_LABELS, Stage, due_dates
from sbomify.apps.compliance.services import report_service
from sbomify.apps.core.authz import ADMINISTER, READ_INTERNAL, can
from sbomify.apps.core.utils import get_team_id_from_session
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin, TeamRoleRequiredMixin


def cra_tabs(request: HttpRequest, team: Any, active: str) -> list[dict[str, Any]]:
    """The CRA page tabs. Assessments are for owners and admins only."""
    tabs = []
    if can(request, "workspace:administer", team):
        tabs.append({"id": "assessments", "label": "Assessments", "href": reverse("compliance:cra_product_list")})
    tabs.append({"id": "reports", "label": "Reports", "href": reverse("compliance:cra_reports")})
    return [{**tab, "active": tab["id"] == active} for tab in tabs]


def _workspace(request: HttpRequest) -> Any:
    team = report_service.get_workspace(get_team_id_from_session(request))
    if team is None:
        raise Http404("Workspace not found")
    return team


class CRAReportListView(GuestAccessBlockedMixin, TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = list(READ_INTERNAL)

    def get(self, request: HttpRequest) -> HttpResponse:
        team = _workspace(request)
        now = timezone.now()
        reports = [
            {"report": report, "next_due": report.next_due(now)} for report in report_service.reports_for_team(team)
        ]
        return render(
            request,
            "compliance/cra_reports.html.j2",
            {
                "tabs": cra_tabs(request, team, "reports"),
                "reports": reports,
                "products": report_service.products_for(team),
                "can_manage_cra_reports": bool(can(request, "cra_report:manage", team)),
            },
        )


class CRAReportCreateView(GuestAccessBlockedMixin, TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = list(ADMINISTER)

    def post(self, request: HttpRequest) -> HttpResponse:
        team = _workspace(request)
        form = CRAReportCreateForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choose the product the report is about.")
            return redirect("compliance:cra_reports")
        data = form.cleaned_data
        result = report_service.create_report(
            team,
            request.user,
            kind=data["kind"],
            product_id=data["product_id"],
            advisory_id=data["advisory_id"] or None,
            aware_at=data["aware_at"] or timezone.now(),
        )
        if not result.ok or result.value is None:
            messages.error(request, result.error or "Could not start the report.")
            if data["advisory_id"]:
                return redirect("core:security_advisory_detail", advisory_id=data["advisory_id"])
            return redirect("compliance:cra_reports")
        return redirect("compliance:cra_report_detail", report_id=result.value.pk)


def _stage_rows(report: Any) -> list[dict[str, Any]]:
    filings = {filing.stage: filing for filing in report.filings.all()}
    notification = filings.get(Stage.NOTIFICATION)
    due = due_dates(
        report.kind,
        aware_at=report.aware_at,
        measure_available_at=report.measure_available_at,
        notification_filed_at=notification.filed_at if notification else None,
    )
    now = timezone.now()
    rows = []
    for stage in DEADLINE_STAGES:
        filing = filings.get(stage)
        due_at = due[stage]
        rows.append(
            {
                "label": STAGE_LABELS[stage],
                "due": due_at,
                "filing": filing,
                "overdue": filing is None and due_at is not None and now > due_at,
            }
        )
    return rows


class CRAReportDetailView(GuestAccessBlockedMixin, TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = list(READ_INTERNAL)

    def _report(self, request: HttpRequest, report_id: str) -> Any:
        report = report_service.get_report(_workspace(request), report_id)
        if report is None:
            raise Http404("Report not found")
        return report

    def get(self, request: HttpRequest, report_id: str) -> HttpResponse:
        report = self._report(request, report_id)
        nxt = report.next_due()
        stage = request.GET.get("stage") or (nxt.stage if nxt else Stage.FINAL_REPORT)
        if stage not in DEADLINE_STAGES:
            stage = Stage.FINAL_REPORT
        layout = report_service.srp_layout(report, stage)
        filable = report_service.filable_stages(report)
        # Filings are append-only, so the form must not fall back on the browser's
        # first option: default to the stage on screen, else the one that is due.
        filing_stage = next((s for s in (stage, nxt.stage if nxt else None) if s in filable), None)
        return render(
            request,
            "compliance/cra_report_detail.html.j2",
            {
                "tabs": cra_tabs(request, report.team, "reports"),
                "report": report,
                "next_due": nxt,
                "stage_rows": _stage_rows(report),
                "copy_stage": stage,
                "copy_stages": [{"value": s, "label": STAGE_LABELS[s]} for s in DEADLINE_STAGES],
                "layout": layout,
                "missing": [row["label"] for row in layout if row["missing"]],
                "edit_rows": [row for row in layout if not row["column"]],
                "filing_stages": [{"value": value, "label": STAGE_LABELS[value]} for value in filable],
                "filing_stage": filing_stage,
                "filings": list(report.filings.all()),
                "can_manage_cra_reports": bool(can(request, "cra_report:manage", report)),
            },
        )

    def post(self, request: HttpRequest, report_id: str) -> HttpResponse:
        report = self._report(request, report_id)
        if not can(request, "cra_report:manage", report):
            return HttpResponseForbidden("Only owners and admins can change a CRA report.")
        action = request.POST.get("action")
        if action == "file":
            self._file(request, report)
        elif action == "save":
            self._save(request, report)
        elif action == "delete" and self._delete(request, report):
            return redirect("compliance:cra_reports")
        return redirect("compliance:cra_report_detail", report_id=report.pk)

    def _file(self, request: HttpRequest, report: Any) -> None:
        form = CRAFilingForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choose what was filed.")
            return
        result = report_service.record_filing(
            report,
            request.user,
            stage=form.cleaned_data["stage"],
            srp_reference=form.cleaned_data["srp_reference"],
            filed_at=form.cleaned_data["filed_at"],
        )
        if result.ok:
            messages.success(request, "Filing recorded.")
        else:
            messages.error(request, result.error or "Could not record the filing.")

    def _save(self, request: HttpRequest, report: Any) -> None:
        form = CRAReportForm(request.POST, kind=report.kind)
        if not form.is_valid():
            labels = ", ".join(str(form.fields[name].label or name) for name in form.errors)
            messages.error(request, f"Nothing was saved. Check these values: {labels}.")
            return
        result = report_service.update_report(report, request.user, values=form.values(), dates=form.dates(report))
        if result.ok:
            messages.success(request, "Report saved.")
        else:
            messages.error(request, result.error or "Could not save the report.")

    def _delete(self, request: HttpRequest, report: Any) -> bool:
        result = report_service.delete_report(report, request.user)
        if result.ok:
            messages.success(request, "Report deleted.")
            return True
        messages.error(request, result.error or "Could not delete the report.")
        return False
