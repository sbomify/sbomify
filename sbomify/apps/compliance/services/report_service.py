"""CRA Article 14 reports: create, edit, record filings, lay out for ENISA's portal.

ENISA's Single Reporting Platform has no API, so a filing is recorded after a
person has submitted the notification in the portal. ``srp_layout`` is the
payload a future submission call would send; ``record_filing`` is what it
would call with the reference ENISA returns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from sbomify.apps.compliance.audit import log_cra_report_event
from sbomify.apps.compliance.models import CRAAssessment, CRAReport, CRAReportFiling
from sbomify.apps.compliance.reporting import (
    STAGE_LABELS,
    Stage,
    fields_for,
    required_fields,
    validate_values,
)
from sbomify.apps.core.services.results import ServiceResult

_ADVISORY_EVENTS = {
    Stage.EARLY_WARNING: "cra_early_warning",
    Stage.NOTIFICATION: "cra_notification",
    Stage.FINAL_REPORT: "cra_final_report",
    Stage.USERS_INFORMED: "users_notified",
}

_PRODUCT_TYPES: dict[str, tuple[str, str]] = {
    CRAAssessment.ProductCategory.DEFAULT: ("Default", ""),
    CRAAssessment.ProductCategory.CLASS_I: ("Important Product with Digital Elements", "Class I"),
    CRAAssessment.ProductCategory.CLASS_II: ("Important Product with Digital Elements", "Class II"),
    CRAAssessment.ProductCategory.CRITICAL: ("Critical Product with Digital Elements", ""),
}

_DATE_FIELDS = ("aware_at", "occurred_at", "measure_available_at")


def _schedule(report: CRAReport) -> None:
    """Queue reminders once the write commits, from the report as it then stands.

    The caller's instance may carry filings prefetched before this write, and
    scheduling from it would queue reminders for a stage just filed.
    """
    from sbomify.apps.compliance.tasks import schedule_reminders

    def schedule() -> None:
        fresh = CRAReport.objects.prefetch_related("filings").filter(pk=report.pk).first()
        if fresh is not None:
            schedule_reminders(fresh)

    transaction.on_commit(schedule)


def _lock(report: CRAReport) -> CRAReport:
    """The report row, locked until the transaction ends and read fresh.

    Editing, filing and deleting each check the filings and then write. Taking
    the same row lock first means a filing cannot land between another
    request's check and its write, and the check reads the filings as they are
    now rather than as the caller fetched them.
    """
    return CRAReport.objects.select_for_update().get(pk=report.pk)


def _prefill(product: Any, advisory: Any) -> dict[str, str]:
    values: dict[str, str] = {"product_name": product.name}
    assessment = CRAAssessment.objects.filter(product=product).first()
    if assessment is not None:
        values["member_states"] = ", ".join(assessment.target_eu_markets or [])
        product_type, product_class = _PRODUCT_TYPES.get(assessment.product_category, ("", ""))
        values["product_type"] = product_type
        values["product_class"] = product_class
        if assessment.support_period_end:
            values["end_of_support"] = "Yes" if assessment.support_period_end < timezone.now().date() else "No"
    if advisory is not None:
        values["title"] = advisory.title[:255]
        values["summary"] = (advisory.summary or advisory.description)[:4000]
        vulnerabilities = list(advisory.vulnerabilities.all())
        exploited = [v for v in vulnerabilities if v.exploitation_status == "known_exploited"] or vulnerabilities
        if exploited:
            vulnerability = exploited[0]
            values["cve_id"] = vulnerability.cve_id
            values["general_information"] = vulnerability.description[:4000]
            values["measures_for_users"] = vulnerability.recommendation[:4000]
    return {key: value for key, value in values.items() if value}


def create_report(
    team: Any,
    user: Any,
    *,
    kind: str,
    product_id: str,
    aware_at: datetime,
    advisory_id: str | None = None,
    occurred_at: datetime | None = None,
    measure_available_at: datetime | None = None,
) -> ServiceResult[CRAReport]:
    from sbomify.apps.core.models import Product
    from sbomify.apps.security_advisories.models import SecurityAdvisory

    if kind not in CRAReport.Kind.values:
        return ServiceResult.failure("Choose a vulnerability or an incident.", status_code=400)
    product = Product.objects.filter(pk=product_id, team=team).first()
    if product is None:
        return ServiceResult.failure("Product not found", status_code=404)

    advisory = None
    if advisory_id:
        advisory = SecurityAdvisory.objects.filter(pk=advisory_id, team=team).first()
        if advisory is None:
            return ServiceResult.failure("Advisory not found", status_code=404)
        if not advisory.products.filter(product=product).exists():
            return ServiceResult.failure("This advisory does not name that product.", status_code=400)
    elif kind == CRAReport.Kind.VULNERABILITY:
        return ServiceResult.failure("A vulnerability report starts from an advisory.", status_code=400)

    try:
        with transaction.atomic():
            report = CRAReport.objects.create(
                team=team,
                kind=kind,
                product=product,
                advisory=advisory,
                aware_at=aware_at,
                occurred_at=occurred_at,
                measure_available_at=measure_available_at,
                srp_fields=_prefill(product, advisory),
                created_by=user,
            )
    except IntegrityError:
        return ServiceResult.failure("This product already has a report for this advisory.", status_code=409)

    log_cra_report_event(
        "cra.report.created",
        user=user,
        team_id=team.pk,
        report_id=report.pk,
        detail={"kind": kind, "product_id": product.pk, "advisory_id": getattr(advisory, "pk", None)},
    )
    _schedule(report)
    return ServiceResult.success(report)


def update_report(
    report: CRAReport,
    user: Any,
    *,
    values: dict[str, Any] | None = None,
    dates: dict[str, datetime | None] | None = None,
) -> ServiceResult[CRAReport]:
    values = values or {}
    errors = validate_values(values)
    if errors:
        return ServiceResult.failure("; ".join(f"{key}: {error}" for key, error in errors.items()), 400)
    dates = dates or {}
    if "aware_at" in dates and dates["aware_at"] is None:
        return ServiceResult.failure("When you became aware is required.", 400)

    with transaction.atomic():
        report = _lock(report)
        if report.is_closed:
            return ServiceResult.failure("The final report is filed, so this report can no longer change.", 409)
        before = {**report.srp_fields, **{name: getattr(report, name) for name in _DATE_FIELDS}}
        merged = dict(report.srp_fields)
        for key, value in values.items():
            text = str(value or "").strip()
            if text:
                merged[key] = text
            else:
                merged.pop(key, None)
        report.srp_fields = merged
        for name, moment in dates.items():
            if name in _DATE_FIELDS:
                setattr(report, name, moment)
        report.save()

    after = {**report.srp_fields, **{name: getattr(report, name) for name in _DATE_FIELDS}}
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    if changed:
        log_cra_report_event(
            "cra.report.updated",
            user=user,
            team_id=report.team_id,
            report_id=report.pk,
            detail={"fields": sorted(changed)},
        )
    _schedule(report)
    return ServiceResult.success(report)


def _snapshot(report: CRAReport) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"srp_fields": dict(report.srp_fields)}
    for name in _DATE_FIELDS:
        moment = getattr(report, name)
        snapshot[name] = moment.isoformat() if moment else None
    return snapshot


def record_filing(
    report: CRAReport,
    user: Any,
    *,
    stage: str,
    srp_reference: str = "",
    filed_at: datetime | None = None,
) -> ServiceResult[CRAReportFiling]:
    """Record a notification a person submitted in ENISA's portal."""
    if stage not in CRAReportFiling.Stage.values:
        return ServiceResult.failure("Choose what was filed.", 400)

    try:
        with transaction.atomic():
            report = _lock(report)
            if report.is_closed and stage != Stage.USERS_INFORMED:
                return ServiceResult.failure("The final report is already filed.", 409)
            if stage != Stage.INTERMEDIATE and report.filings.filter(stage=stage).exists():
                return ServiceResult.failure(f"The {STAGE_LABELS[stage].lower()} is already recorded.", 409)
            filing = CRAReportFiling.objects.create(
                report=report,
                stage=stage,
                srp_reference=srp_reference.strip()[:100],
                filed_at=filed_at or timezone.now(),
                filed_by=user,
                snapshot=_snapshot(report),
            )
            event_type = _ADVISORY_EVENTS.get(stage)
            if event_type and report.advisory_id:
                from sbomify.apps.security_advisories.models import AdvisoryEvent

                AdvisoryEvent.objects.create(
                    advisory_id=report.advisory_id,
                    event_type=event_type,
                    actor=user,
                    payload={
                        "report_id": report.pk,
                        "product": report.product.name,
                        "srp_reference": filing.srp_reference,
                        "filed_at": filing.filed_at.isoformat(),
                    },
                )
    except IntegrityError:
        return ServiceResult.failure(f"The {STAGE_LABELS[stage].lower()} is already recorded.", 409)

    log_cra_report_event(
        "cra.report.filed",
        user=user,
        team_id=report.team_id,
        report_id=report.pk,
        detail={"stage": stage, "srp_reference": filing.srp_reference, "filed_at": filing.filed_at},
    )
    _schedule(report)
    return ServiceResult.success(filing)


def delete_report(report: CRAReport, user: Any) -> ServiceResult[None]:
    with transaction.atomic():
        report = _lock(report)
        if report.filings.exists():
            return ServiceResult.failure("A report with a recorded filing is kept as evidence.", 409)
        report_id = report.pk  # delete() clears it
        report.delete()
    log_cra_report_event(
        "cra.report.deleted", user=user, team_id=report.team_id, report_id=report_id, detail={"kind": report.kind}
    )
    return ServiceResult.success(None)


def get_report(team: Any, report_id: str) -> CRAReport | None:
    return (
        CRAReport.objects.select_related("product", "advisory")
        .prefetch_related("filings")
        .filter(pk=report_id, team=team)
        .first()
    )


def reports_for_team(team: Any) -> list[CRAReport]:
    """Open reports first, soonest deadline first; then closed ones."""
    reports = list(
        CRAReport.objects.select_related("product", "advisory").prefetch_related("filings").filter(team=team)
    )
    now = timezone.now()

    def order(report: CRAReport) -> tuple[int, float]:
        nxt = report.next_due(now)
        if nxt is None:
            return (2, 0.0)
        return (0, nxt.due.timestamp()) if nxt.due else (1, 0.0)

    return sorted(reports, key=order)


def _display(report: CRAReport, field: Any) -> str:
    if field.column:
        moment = getattr(report, field.column)
        return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC") if moment else ""
    return str(report.srp_fields.get(field.id, ""))


def srp_layout(report: CRAReport, stage: str) -> list[dict[str, Any]]:
    """Every field of the portal's form for this report, in the portal's order."""
    required = {field.id for field in required_fields(report.kind, stage)}
    rows = []
    for field in fields_for(report.kind):
        value = _display(report, field)
        rows.append(
            {
                "id": field.id,
                "label": field.label,
                "kind": field.kind,
                "value": value,
                "max_length": field.max_length,
                "choices": list(field.choices),
                "column": field.column,
                "required": field.id in required,
                "missing": field.id in required and not value.strip(),
            }
        )
    return rows


def advisory_reporting(team: Any, advisory_pk: str) -> dict[str, Any]:
    """What the advisory page shows: per tracked product, its report or a way to start one."""
    from sbomify.apps.security_advisories.models import AdvisoryProduct, AdvisoryVulnerability

    known_exploited = AdvisoryVulnerability.objects.filter(
        advisory_id=advisory_pk,
        advisory__team=team,
        exploitation_status=AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED,
    ).exists()
    reports = {
        report.product_id: report
        for report in CRAReport.objects.prefetch_related("filings").filter(advisory_id=advisory_pk, team=team)
    }
    now = timezone.now()
    rows = []
    for row in AdvisoryProduct.objects.filter(advisory_id=advisory_pk, product__isnull=False).select_related("product"):
        if row.product is None:
            continue
        report = reports.get(row.product.pk)
        rows.append(
            {
                "product_id": row.product.pk,
                "product_name": row.product.name,
                "report": report,
                "next_due": report.next_due(now) if report else None,
            }
        )
    return {"known_exploited": known_exploited, "rows": rows, "show": known_exploited or bool(reports)}


def get_workspace(team_id: Any) -> Any:
    from sbomify.apps.teams.models import Workspace

    return Workspace.objects.filter(pk=team_id).first() if team_id else None


def products_for(team: Any) -> list[dict[str, str]]:
    """The workspace's products, for choosing which one an incident affects."""
    from sbomify.apps.core.models import Product

    return [
        {"value": product_id, "label": name}
        for product_id, name in Product.objects.filter(team=team).order_by("name").values_list("id", "name")
    ]
