"""CRA Article 14 reporting rules: the deadlines and the ENISA form's fields.

ENISA's Single Reporting Platform (SRP) takes notifications through a web
portal only, so sbomify does not submit anything. It prepares each field the
way the portal asks for it, tracks the deadlines and records what was filed.

The field list follows ENISA's "CRA SRP Glossary", version 1.6 of 21 October
2026. Three of its 42 entries are not fields here: the notification type is
the report's kind, the manufacturer name is shown read-only by the portal, and
the CSIRT note is the CSIRT's. Since 1.6 a later stage does not repeat the
early warning: each field says what each stage does with it, and most early
warning fields are not on the later forms at all.
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


class Need:
    """What the portal does with a field at one stage, in the glossary's words."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    # "By default copied from previous step": on the form, prefilled from the last stage.
    COPIED = "copied"
    # Not on that stage's form. A later stage only carries what is new.
    NOT_ASKED = "not_asked"


_R, _O, _C, _NA = Need.REQUIRED, Need.OPTIONAL, Need.COPIED, Need.NOT_ASKED

# The same three columns as the glossary: early warning, notification, final report.
_EARLY_WARNING_ONLY = (_R, _NA, _NA)
_EARLY_WARNING_IF_KNOWN = (_O, _NA, _NA)
_NOTIFICATION_NEEDS = (_O, _R, _NA)
_FINAL_REPORT_NEEDS = (_O, _O, _R)


@dataclass(frozen=True)
class SRPField:
    id: str
    label: str
    section: str  # "common", "vulnerability" or "incident"
    # What each deadline stage does with it, in DEADLINE_STAGES order.
    needs: tuple[str, str, str]
    kind: str = "text"  # "text", "longtext", "choice" or "datetime"
    max_length: int | None = None
    choices: tuple[str, ...] = ()
    # A report column rather than a JSON value: the dates drive the deadlines.
    column: str | None = None

    def need_at(self, stage: str) -> str:
        """An intermediate report has no column of its own, so it is read as the final report."""
        return self.needs[_STAGE_ORDER.get(stage, len(DEADLINE_STAGES) - 1)]

    def on_form(self, stage: str) -> bool:
        return self.need_at(stage) != Need.NOT_ASKED


_YES_NO = ("Yes", "No")
_STAGE_ORDER = {stage: index for index, stage in enumerate(DEADLINE_STAGES)}

# In the portal's order, under ENISA's labels.
SRP_FIELDS: tuple[SRPField, ...] = (
    SRPField("title", "Title", "common", _EARLY_WARNING_ONLY, max_length=255),
    SRPField("summary", "Summary", "common", _EARLY_WARNING_ONLY, "longtext", 4000),
    SRPField(
        "member_states",
        "Member States where product available (CSIRT Designated as Coordinator and Concerned CSIRTs)",
        "common",
        _EARLY_WARNING_ONLY,
    ),
    SRPField("product_name", "Product Name", "common", _EARLY_WARNING_ONLY, max_length=255),
    SRPField("product_version", "Product Version", "common", _EARLY_WARNING_ONLY, max_length=255),
    SRPField("additional_information", "Additional Information", "common", _EARLY_WARNING_IF_KNOWN, "longtext", 255),
    SRPField(
        "product_type",
        "Product Type (Default/Important/Critical)",
        "common",
        _EARLY_WARNING_IF_KNOWN,
        "choice",
        choices=("Default", "Important Product with Digital Elements", "Critical Product with Digital Elements"),
    ),
    SRPField(
        "product_class", "Product class", "common", _EARLY_WARNING_IF_KNOWN, "choice", choices=("Class I", "Class II")
    ),
    SRPField("product_category", "Product category", "common", _EARLY_WARNING_IF_KNOWN, max_length=255),
    SRPField(
        "end_of_support", "End of the support indicator", "common", _EARLY_WARNING_IF_KNOWN, "choice", choices=_YES_NO
    ),
    SRPField("component_name", "Component name", "common", _EARLY_WARNING_IF_KNOWN, max_length=255),
    SRPField(
        "measure_expected",
        "Mitigating measure expected shortly",
        "common",
        _EARLY_WARNING_IF_KNOWN,
        "choice",
        choices=_YES_NO,
    ),
    SRPField("user_action", "User Action able to reduce impact", "common", _EARLY_WARNING_IF_KNOWN, "longtext", 4000),
    SRPField("sensitivity", "Considered sensitivity of information", "common", (_O, _O, _NA), max_length=255),
    SRPField(
        "measures_taken", "Corrective or mitigating measures taken", "common", _FINAL_REPORT_NEEDS, "longtext", 2000
    ),
    SRPField(
        "measures_for_users",
        "Corrective or mitigating measures that users can take",
        "common",
        _FINAL_REPORT_NEEDS,
        "longtext",
        4000,
    ),
    SRPField("attack_vector", "Attack vector", "common", (_NA, _O, _NA), max_length=255),
    SRPField("cve_id", "CVE ID", "vulnerability", _EARLY_WARNING_IF_KNOWN, max_length=255),
    SRPField("euvd_id", "EUVD ID", "vulnerability", _EARLY_WARNING_IF_KNOWN, max_length=255),
    SRPField("general_information", "General information", "vulnerability", _NOTIFICATION_NEEDS, "longtext", 4000),
    SRPField(
        "measure_available_at",
        "Date when corrective or mitigating measure has been available",
        "vulnerability",
        _FINAL_REPORT_NEEDS,
        "datetime",
        column="measure_available_at",
    ),
    SRPField(
        "measure_details",
        "Details about the security update/corrective measure available",
        "vulnerability",
        _FINAL_REPORT_NEEDS,
        "longtext",
        2000,
    ),
    SRPField(
        "vulnerability_severity",
        "Description of the severity of the vulnerability",
        "vulnerability",
        _FINAL_REPORT_NEEDS,
        "longtext",
        4000,
    ),
    SRPField(
        "vulnerability_impact",
        "Description of the impact of the vulnerability",
        "vulnerability",
        _FINAL_REPORT_NEEDS,
        "longtext",
        4000,
    ),
    SRPField(
        "vulnerability_aware_at",
        "Date and time when you become aware of the Actively Exploited Vulnerability",
        "vulnerability",
        _EARLY_WARNING_ONLY,
        "datetime",
        column="aware_at",
    ),
    SRPField(
        "vulnerability_occurred_at",
        "Date and time when the Actively Exploited Vulnerability occurred (UTC time)",
        "vulnerability",
        (_O, _C, _NA),
        "datetime",
        column="occurred_at",
    ),
    # The portal requires it at the final report "if available", so it is not
    # counted as missing.
    SRPField(
        "malicious_actor",
        "Malicious actor that has exploited/is exploiting the vulnerability",
        "vulnerability",
        (_O, _O, _O),
        max_length=100,
    ),
    SRPField("pec", "Particularly Exceptional Circumstances (PEC)", "vulnerability", (_NA, _O, _NA), max_length=255),
    SRPField("pec_delay_reason", "PEC Delay Reason", "vulnerability", (_NA, _O, _NA), max_length=255),
    SRPField(
        "further_information", "Please provide further information", "vulnerability", (_NA, _O, _NA), "longtext", 800
    ),
    SRPField(
        "suspected_unlawful",
        "Incident is suspected of unlawful or malicious acts",
        "incident",
        (_R, _C, _NA),
        max_length=255,
    ),
    SRPField(
        "incident_nature",
        "General information, about the nature of the incident",
        "incident",
        _NOTIFICATION_NEEDS,
        "longtext",
        4000,
    ),
    SRPField(
        "incident_mitigation",
        "Applied and ongoing mitigation measures",
        "incident",
        _FINAL_REPORT_NEEDS,
        "longtext",
        4000,
    ),
    SRPField(
        "incident_severity",
        "Detailed description of the Severity of the incident",
        "incident",
        _FINAL_REPORT_NEEDS,
        "longtext",
        4000,
    ),
    SRPField(
        "incident_impact",
        "Detailed description of the Impact of the incident",
        "incident",
        _FINAL_REPORT_NEEDS,
        "longtext",
        4000,
    ),
    SRPField(
        "root_cause",
        "Type of Threat or root cause that is likely to have triggered incident",
        "incident",
        _FINAL_REPORT_NEEDS,
        max_length=255,
    ),
    SRPField(
        "incident_aware_at",
        "Date and time when you become aware of the incident (UTC time)",
        "incident",
        _EARLY_WARNING_ONLY,
        "datetime",
        column="aware_at",
    ),
    SRPField(
        "incident_occurred_at",
        "Date and time when the incident occurred (UTC time)",
        "incident",
        (_O, _O, _NA),
        "datetime",
        column="occurred_at",
    ),
    SRPField(
        "initial_assessment", "Initial assessment of the incident", "incident", _NOTIFICATION_NEEDS, "longtext", 4000
    ),
    SRPField("ar_note", "AR Note", "common", (_O, _O, _O), "longtext"),
)

FIELDS_BY_ID = {field.id: field for field in SRP_FIELDS}


def fields_for(kind: str) -> list[SRPField]:
    return [field for field in SRP_FIELDS if field.section in ("common", kind)]


def required_fields(kind: str, stage: str) -> list[SRPField]:
    """What the portal needs at ``stage`` itself. What an earlier stage needed was filed with it."""
    return [field for field in fields_for(kind) if field.need_at(stage) == Need.REQUIRED]


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
