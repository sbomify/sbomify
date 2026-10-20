"""CRA Article 14 reporting rules: the deadlines and the ENISA form's fields.

ENISA's Single Reporting Platform (SRP) takes notifications through a web
portal only, so sbomify does not submit anything. It prepares each field the
way the portal asks for it, tracks the deadlines and records what was filed.

The field list follows ENISA's "CRA SRP Glossary". Two of its 41 entries are
left out because the manufacturer never fills them: the manufacturer name,
which the portal shows read-only, and the CSIRT note, which is the CSIRT's.
When ENISA changes the form, this list is the only thing to edit: report
values live in one JSON column keyed by these ids, so no migration follows.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


class Stage:
    EARLY_WARNING = "early_warning"
    NOTIFICATION = "notification"
    INTERMEDIATE = "intermediate"
    FINAL_REPORT = "final_report"
    USERS_INFORMED = "users_informed"


STAGE_LABELS = {
    Stage.EARLY_WARNING: "Early warning",
    Stage.NOTIFICATION: "Notification",
    Stage.INTERMEDIATE: "Intermediate report",
    Stage.FINAL_REPORT: "Final report",
    Stage.USERS_INFORMED: "Users informed",
}

# The stages with a legal deadline, in the order they fall due.
DEADLINE_STAGES = (Stage.EARLY_WARNING, Stage.NOTIFICATION, Stage.FINAL_REPORT)

# Regulation (EU) 2024/2847, Article 14. An actively exploited vulnerability
# and a severe incident each need an early warning within 24 hours of the
# manufacturer becoming aware (14(2)(a), 14(4)(a)) and a notification within
# 72 hours (14(2)(b), 14(4)(b)). The final report is due no later than 14 days
# after a corrective or mitigating measure is available for a vulnerability
# (14(2)(c)), and within one month after the notification for an incident
# (14(4)(c)).
EARLY_WARNING_WITHIN = timedelta(hours=24)
NOTIFICATION_WITHIN = timedelta(hours=72)
VULNERABILITY_FINAL_REPORT_WITHIN = timedelta(days=14)


def add_one_month(moment: datetime) -> datetime:
    """The same day next month, or that month's last day when it is shorter."""
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def due_dates(
    kind: str,
    *,
    aware_at: datetime,
    measure_available_at: datetime | None,
    notification_filed_at: datetime | None,
) -> dict[str, datetime | None]:
    """When each deadline stage is due. None means it cannot be dated yet."""
    if kind == "vulnerability":
        final = measure_available_at + VULNERABILITY_FINAL_REPORT_WITHIN if measure_available_at else None
    else:
        final = add_one_month(notification_filed_at) if notification_filed_at else None
    return {
        Stage.EARLY_WARNING: aware_at + EARLY_WARNING_WITHIN,
        Stage.NOTIFICATION: aware_at + NOTIFICATION_WITHIN,
        Stage.FINAL_REPORT: final,
    }


@dataclass(frozen=True)
class NextDue:
    stage: str
    due: datetime | None
    overdue: bool

    @property
    def label(self) -> str:
        return STAGE_LABELS[self.stage]


def open_deadlines(
    kind: str,
    aware_at: datetime,
    measure_available_at: datetime | None,
    *,
    filed: dict[str, datetime],
) -> list[tuple[str, datetime | None]]:
    """Every deadline stage not yet filed with its due date, in order.

    Empty once the final report is filed, even if a stage before it never was:
    the final report closes the report.
    """
    if Stage.FINAL_REPORT in filed:
        return []
    due = due_dates(
        kind,
        aware_at=aware_at,
        measure_available_at=measure_available_at,
        notification_filed_at=filed.get(Stage.NOTIFICATION),
    )
    return [(stage, due[stage]) for stage in DEADLINE_STAGES if stage not in filed]


def next_due(
    kind: str,
    aware_at: datetime,
    measure_available_at: datetime | None,
    *,
    filed: dict[str, datetime],
    now: datetime,
) -> NextDue | None:
    """The first deadline stage not yet filed, or None once the final report is."""
    for stage, moment in open_deadlines(kind, aware_at, measure_available_at, filed=filed):
        return NextDue(stage, moment, moment is not None and now > moment)
    return None


@dataclass(frozen=True)
class SRPField:
    id: str
    label: str
    section: str  # "common", "vulnerability" or "incident"
    kind: str = "text"  # "text", "longtext", "choice" or "datetime"
    max_length: int | None = None
    # The first stage the portal requires it for; None when it never does.
    required_from: str | None = None
    choices: tuple[str, ...] = ()
    # A report column rather than a JSON value: the dates drive the deadlines.
    column: str | None = None


_YES_NO = ("Yes", "No")
_EW, _N, _FR = Stage.EARLY_WARNING, Stage.NOTIFICATION, Stage.FINAL_REPORT

# In the portal's order, under ENISA's labels.
SRP_FIELDS: tuple[SRPField, ...] = (
    SRPField("title", "Title", "common", max_length=255, required_from=_EW),
    SRPField("summary", "Summary", "common", "longtext", 4000, _EW),
    SRPField("member_states", "Member States where product available (Concerned CSIRT)", "common", required_from=_EW),
    SRPField("product_name", "Product Name", "common", max_length=255, required_from=_EW),
    SRPField("product_version", "Product Version", "common", max_length=255, required_from=_EW),
    SRPField(
        "product_type",
        "Product Type (Default/Important/Critical)",
        "common",
        "choice",
        choices=("Default", "Important Product with Digital Elements", "Critical Product with Digital Elements"),
    ),
    SRPField("product_class", "Product class", "common", "choice", choices=("Class I", "Class II")),
    SRPField("product_category", "Product category", "common", max_length=255),
    SRPField("end_of_support", "End of support indicator", "common", "choice", choices=_YES_NO),
    SRPField("component_name", "Component name", "common", max_length=255),
    SRPField("measure_expected", "Mitigating measure expected shortly", "common", "choice", choices=_YES_NO),
    SRPField("user_action", "User Action able to reduce impact", "common", "longtext", 4000),
    SRPField("sensitivity", "Considered sensitivity of information", "common", max_length=255),
    SRPField("measures_taken", "Corrective or mitigating measures taken", "common", "longtext", 2000, _FR),
    SRPField(
        "measures_for_users", "Corrective or mitigating measures that users can take", "common", "longtext", 4000, _FR
    ),
    SRPField("attack_vector", "Attack vector", "common", max_length=255),
    SRPField("cve_id", "CVE ID", "vulnerability", max_length=255),
    SRPField("euvd_id", "EUVD ID", "vulnerability", max_length=255),
    SRPField("general_information", "General information", "vulnerability", "longtext", 4000, _N),
    SRPField(
        "measure_available_at",
        "Date when corrective or mitigating measure has been available",
        "vulnerability",
        "datetime",
        required_from=_FR,
        column="measure_available_at",
    ),
    SRPField(
        "measure_details",
        "Details about the security update/corrective measure available",
        "vulnerability",
        "longtext",
        2000,
        _FR,
    ),
    SRPField(
        "vulnerability_severity",
        "Full description of the Severity of the vulnerability",
        "vulnerability",
        "longtext",
        4000,
        _FR,
    ),
    SRPField(
        "vulnerability_impact",
        "Full description of the Impact of the vulnerability",
        "vulnerability",
        "longtext",
        4000,
        _FR,
    ),
    SRPField(
        "vulnerability_aware_at",
        "Date and time when you become aware of the Actively Exploited Vulnerability",
        "vulnerability",
        "datetime",
        required_from=_EW,
        column="aware_at",
    ),
    SRPField(
        "vulnerability_occurred_at",
        "Date and time when the Actively Exploited Vulnerability occurred (UTC time)",
        "vulnerability",
        "datetime",
        required_from=_N,
        column="occurred_at",
    ),
    # The portal requires it at the final report "if available", so it is not
    # counted as missing.
    SRPField(
        "malicious_actor",
        "Malicious actor that has exploited/is exploiting the vulnerability",
        "vulnerability",
        max_length=100,
    ),
    SRPField("pec", "Particularly Exceptional Circumstances (PEC)", "vulnerability", max_length=255),
    SRPField("pec_delay_reason", "PEC Delay Reason", "vulnerability", max_length=255),
    SRPField("further_information", "Please provide further information", "vulnerability", "longtext", 800),
    SRPField(
        "suspected_unlawful",
        "Incident is suspected of unlawful or malicious acts",
        "incident",
        max_length=255,
        required_from=_EW,
    ),
    SRPField(
        "incident_nature", "General information, about the nature of the incident", "incident", "longtext", 4000, _N
    ),
    SRPField("incident_mitigation", "Applied and ongoing mitigation measures", "incident", "longtext", 4000, _FR),
    SRPField(
        "incident_severity", "Detailed description of the Severity of the incident", "incident", "longtext", 4000, _FR
    ),
    SRPField(
        "incident_impact", "Detailed description of the Impact of the incident", "incident", "longtext", 4000, _FR
    ),
    SRPField(
        "root_cause",
        "Type of Threat or root cause that is likely to have triggered incident",
        "incident",
        max_length=255,
        required_from=_FR,
    ),
    SRPField(
        "incident_aware_at",
        "Date and time when you become aware of the incident (UTC time)",
        "incident",
        "datetime",
        required_from=_EW,
        column="aware_at",
    ),
    SRPField(
        "incident_occurred_at",
        "Date and time when the incident occurred (UTC time)",
        "incident",
        "datetime",
        required_from=_N,
        column="occurred_at",
    ),
    SRPField("initial_assessment", "Initial assessment of the incident", "incident", "longtext", 4000, _N),
    SRPField("ar_note", "AR Note", "common", "longtext"),
)

FIELDS_BY_ID = {field.id: field for field in SRP_FIELDS}
_STAGE_ORDER = {stage: index for index, stage in enumerate(DEADLINE_STAGES)}


def fields_for(kind: str) -> list[SRPField]:
    return [field for field in SRP_FIELDS if field.section in ("common", kind)]


def required_fields(kind: str, stage: str) -> list[SRPField]:
    """What the portal needs at ``stage``, which includes every earlier stage's needs."""
    limit = _STAGE_ORDER.get(stage, len(DEADLINE_STAGES) - 1)
    return [
        field
        for field in fields_for(kind)
        if field.required_from is not None and _STAGE_ORDER[field.required_from] <= limit
    ]


def missing_fields(kind: str, stage: str, values: dict[str, Any]) -> list[str]:
    """Ids of the fields ``stage`` requires that are still empty."""
    return [field.id for field in required_fields(kind, stage) if not str(values.get(field.id) or "").strip()]


def validate_values(values: dict[str, Any], kind: str | None = None) -> dict[str, str]:
    """Field id to error, for the JSON-stored values. Column fields are not stored here.

    With ``kind``, a field that only the other kind of report has is refused too:
    it would be stored but never shown or sent.
    """
    errors: dict[str, str] = {}
    allowed = {field.id for field in fields_for(kind)} if kind else None
    for key, value in values.items():
        field = FIELDS_BY_ID.get(key)
        if field is None or field.column:
            errors[key] = "This is not a field of the ENISA form."
        elif allowed is not None and key not in allowed:
            errors[key] = f"This field is not on a {kind} report."
        elif field.choices and value and value not in field.choices:
            errors[key] = f"Choose one of: {', '.join(field.choices)}."
        elif field.max_length is not None and len(str(value or "")) > field.max_length:
            errors[key] = f"The portal accepts at most {field.max_length} characters."
    return errors
