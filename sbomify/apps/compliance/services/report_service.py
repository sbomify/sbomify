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
    DEADLINE_STAGES,
    STAGE_LABELS,
    Stage,
    fields_for,
    required_fields,
    validate_values,
)
from sbomify.apps.core.services.results import ServiceResult
from sbomify.logging import getLogger

logger = getLogger(__name__)

_ADVISORY_EVENTS = {
    Stage.EARLY_WARNING: "cra_early_warning",
    Stage.NOTIFICATION: "cra_notification",
    Stage.INTERMEDIATE: "cra_intermediate_report",
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
    scheduling from it would queue reminders for a stage just filed, so
    ``schedule_pending`` reads the report afresh. The report is marked pending
    with the write, and the mark survives a broker outage, so the outage neither
    fails a save that already committed nor loses its reminders: the mark stays
    for ``dispatch_pending_reminders``.
    """
    from sbomify.apps.compliance.tasks import schedule_pending

    CRAReport.objects.filter(pk=report.pk).update(reminders_pending=True)
    report_id = report.pk
    transaction.on_commit(lambda: schedule_pending(report_id))


def _lock(report: CRAReport) -> CRAReport:
    """The report row, locked until the transaction ends and read fresh.

    Editing, filing and deleting each check the filings and then write. Taking
    the same row lock first means a filing cannot land between another
    request's check and its write, and the check reads the filings as they are
    now rather than as the caller fetched them.
    """
    return CRAReport.objects.select_for_update().get(pk=report.pk)


_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def applicable_vulnerabilities(advisory: Any, product: Any) -> list[Any]:
    """The advisory's vulnerabilities that affect this product, known exploited and most severe first.

    A vulnerability applies unless the product's own status, or failing that
    the advisory's portfolio-wide one, says not affected or false positive.
    With no status at all it applies: the advisory names the product, and an
    unrecorded status is no reason to skip a reporting duty. Fixed still
    applies, since the final report falls due after the fix.
    """
    advisory_product = advisory.products.filter(product=product).first()
    if advisory_product is None:
        return []
    return _applicable(_advisory_vulnerabilities(advisory), advisory_product)


def _advisory_vulnerabilities(advisory: Any) -> list[Any]:
    """Every vulnerability on the advisory with its statuses, loaded once for any number of products."""
    return list(advisory.vulnerabilities.prefetch_related("product_statuses"))


def _applicable(vulnerabilities: list[Any], advisory_product: Any) -> list[Any]:
    from sbomify.apps.security_advisories.models import AdvisoryProductStatus, AdvisoryVulnerability

    def applies(vulnerability: Any) -> bool:
        statuses = list(vulnerability.product_statuses.all())
        status = next((s for s in statuses if s.advisory_product_id == advisory_product.pk), None) or next(
            (s for s in statuses if s.advisory_product_id is None and s.advisory_component_id is None), None
        )
        return status is None or status.status not in AdvisoryProductStatus.SUPPRESSING_STATES

    exploited = AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED
    found = [v for v in vulnerabilities if applies(v)]
    return sorted(found, key=lambda v: (v.exploitation_status != exploited, -_SEVERITY_RANK.get(v.severity, 0)))


def _known_exploited(vulnerabilities: list[Any]) -> list[Any]:
    from sbomify.apps.security_advisories.models import AdvisoryVulnerability

    return [
        v for v in vulnerabilities if v.exploitation_status == AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED
    ]


def _prefill(product: Any, advisory: Any, kind: str) -> dict[str, str]:
    """What sbomify already knows, limited to the fields a ``kind`` report has."""
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
        applicable = applicable_vulnerabilities(advisory, product)
        if applicable:
            vulnerability = applicable[0]
            values["cve_id"] = vulnerability.cve_id
            values["general_information"] = vulnerability.description[:4000]
            values["measures_for_users"] = vulnerability.recommendation[:4000]
    on_form = {field.id for field in fields_for(kind)}
    return {key: value for key, value in values.items() if value and key in on_form}


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
        if kind == CRAReport.Kind.VULNERABILITY and not _known_exploited(applicable_vulnerabilities(advisory, product)):
            return ServiceResult.failure(
                "No known exploited vulnerability in this advisory affects that product.", status_code=400
            )
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
                srp_fields=_prefill(product, advisory, kind),
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
    revision: str | None = None,
) -> ServiceResult[CRAReport]:
    """Change the report's values and dates.

    ``revision`` is the report's ``revision`` from the read the edit is based
    on. A form posts every field, so an edit made since then would be silently
    undone, deadlines included.
    """
    values = values or {}
    errors = validate_values(values, report.kind)
    if errors:
        return ServiceResult.failure("; ".join(f"{key}: {error}" for key, error in errors.items()), 400)
    dates = dates or {}
    if "aware_at" in dates and dates["aware_at"] is None:
        return ServiceResult.failure("When you became aware is required.", 400)

    with transaction.atomic():
        report = _lock(report)
        if report.is_closed:
            return ServiceResult.failure("The final report is filed, so this report can no longer change.", 409)
        if revision is not None and revision != report.revision:
            return ServiceResult.failure(
                "This report changed after you opened it. Reload the page to see the changes, then save again.", 409
            )
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


def _filing_note(report: CRAReport, filing: CRAReportFiling) -> str:
    note = (
        f"{STAGE_LABELS[filing.stage]} for {report.product.name} filed in ENISA's portal "
        f"on {filing.filed_at.astimezone(UTC):%d %b %Y %H:%M} UTC"
    )
    return f"{note}, reference {filing.srp_reference}." if filing.srp_reference else f"{note}."


def filable_stages(report: CRAReport) -> list[str]:
    """What can still be recorded: intermediate reports repeat, and a closed report takes only users informed."""
    filed = report.filed_stages()
    closed = Stage.FINAL_REPORT in filed
    return [
        stage
        for stage in CRAReportFiling.Stage.values
        if (not closed or stage == Stage.USERS_INFORMED) and (stage == Stage.INTERMEDIATE or stage not in filed)
    ]


def record_filing(
    report: CRAReport,
    user: Any,
    *,
    stage: str,
    srp_reference: str = "",
    filed_at: datetime | None = None,
    revision: str | None = None,
) -> ServiceResult[CRAReportFiling]:
    """Record a notification a person submitted in ENISA's portal.

    ``revision`` is the report's ``revision`` when its values were copied into
    the portal. The filing keeps a snapshot of the report, so an edit made
    since then would be recorded as filed when it never was.
    """
    if stage not in CRAReportFiling.Stage.values:
        return ServiceResult.failure("Choose what was filed.", 400)
    srp_reference = srp_reference.strip()
    # Filings are append-only, so a reference cut short here could never be corrected.
    limit = CRAReportFiling._meta.get_field("srp_reference").max_length or 0
    if len(srp_reference) > limit:
        return ServiceResult.failure(f"The ENISA reference is at most {limit} characters.", status_code=400)

    try:
        with transaction.atomic():
            report = _lock(report)
            if revision is not None and revision != report.revision:
                return ServiceResult.failure(
                    "This report changed after you opened it. Check the values, then record the filing again.", 409
                )
            if stage not in filable_stages(report):
                if report.is_closed and stage != Stage.USERS_INFORMED:
                    return ServiceResult.failure("The final report is already filed.", 409)
                return ServiceResult.failure(f"The {STAGE_LABELS[stage].lower()} is already recorded.", 409)
            filing = CRAReportFiling.objects.create(
                report=report,
                stage=stage,
                srp_reference=srp_reference,
                filed_at=filed_at or timezone.now(),
                filed_by=user,
                filer=(user.email or user.username) if user else "",
                snapshot=_snapshot(report),
            )
            event_type = _ADVISORY_EVENTS.get(stage)
            if event_type and report.advisory_id:
                from sbomify.apps.security_advisories.models import AdvisoryEvent

                AdvisoryEvent.objects.create(
                    advisory_id=report.advisory_id,
                    event_type=event_type,
                    actor=user,
                    # The timeline shows the body, so it carries what tells two
                    # products' filings on one advisory apart.
                    body=_filing_note(report, filing),
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


def filing_layout(filing: CRAReportFiling) -> list[dict[str, Any]]:
    """The fields a filing carried, as its snapshot holds them, in the portal's order."""
    snapshot = filing.snapshot
    as_filed = CRAReport(
        kind=filing.report.kind,
        srp_fields=dict(snapshot.get("srp_fields", {})),
        **{name: datetime.fromisoformat(snapshot[name]) if snapshot.get(name) else None for name in _DATE_FIELDS},
    )
    stage = filing.stage if filing.stage in DEADLINE_STAGES else Stage.FINAL_REPORT
    return [row for row in srp_layout(as_filed, stage) if row["value"]]


def advisory_reporting(team: Any, advisory_pk: str) -> dict[str, Any]:
    """What the advisory page shows: per tracked product, its report or a way to start one."""
    from sbomify.apps.security_advisories.models import AdvisoryProduct, SecurityAdvisory

    advisory = SecurityAdvisory.objects.filter(pk=advisory_pk, team=team).first()
    reports = {
        report.product_id: report
        for report in CRAReport.objects.prefetch_related("filings").filter(advisory_id=advisory_pk, team=team)
    }
    now = timezone.now()
    links = list(
        AdvisoryProduct.objects.filter(advisory_id=advisory_pk, product__isnull=False).select_related("product")
    )
    # Loaded once, only when some product has no report yet, then read for each.
    vulnerabilities = (
        _advisory_vulnerabilities(advisory)
        if advisory is not None and any(row.product_id not in reports for row in links)
        else []
    )
    rows = []
    for row in links:
        if row.product is None:
            continue
        report = reports.get(row.product.pk)
        rows.append(
            {
                "product_id": row.product.pk,
                "product_name": row.product.name,
                "report": report,
                "next_due": report.next_due(now) if report else None,
                # Per product: a status saying it is not affected leaves nothing to report for it.
                "can_start": report is None and bool(_known_exploited(_applicable(vulnerabilities, row))),
            }
        )
    known_exploited = any(row["can_start"] for row in rows)
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
