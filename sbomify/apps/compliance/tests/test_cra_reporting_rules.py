"""Article 14 deadlines and the SRP field registry. Pure functions, no database."""

from datetime import UTC, datetime, timedelta

import pytest

from sbomify.apps.compliance import reporting
from sbomify.apps.compliance.reporting import Stage

AWARE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_the_early_warning_is_due_a_day_after_becoming_aware():
    due = reporting.due_dates("vulnerability", aware_at=AWARE, measure_available_at=None, notification_filed_at=None)

    assert due[Stage.EARLY_WARNING] == AWARE + timedelta(hours=24)


def test_the_notification_is_due_three_days_after_becoming_aware():
    due = reporting.due_dates("incident", aware_at=AWARE, measure_available_at=None, notification_filed_at=None)

    assert due[Stage.NOTIFICATION] == AWARE + timedelta(hours=72)


def test_a_vulnerability_final_report_has_no_due_date_until_a_fix_exists():
    due = reporting.due_dates("vulnerability", aware_at=AWARE, measure_available_at=None, notification_filed_at=None)

    assert due[Stage.FINAL_REPORT] is None


def test_a_vulnerability_final_report_is_due_fourteen_days_after_the_fix():
    fix = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

    due = reporting.due_dates("vulnerability", aware_at=AWARE, measure_available_at=fix, notification_filed_at=None)

    assert due[Stage.FINAL_REPORT] == fix + timedelta(days=14)


def test_an_incident_final_report_is_due_a_month_after_the_notification():
    filed = datetime(2026, 10, 3, 8, 30, tzinfo=UTC)

    due = reporting.due_dates("incident", aware_at=AWARE, measure_available_at=None, notification_filed_at=filed)

    assert due[Stage.FINAL_REPORT] == datetime(2026, 11, 3, 8, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("filed", "expected"),
    [
        (datetime(2026, 1, 31, 10, 0, tzinfo=UTC), datetime(2026, 2, 28, 10, 0, tzinfo=UTC)),
        (datetime(2028, 1, 31, 10, 0, tzinfo=UTC), datetime(2028, 2, 29, 10, 0, tzinfo=UTC)),
        (datetime(2026, 12, 15, 10, 0, tzinfo=UTC), datetime(2027, 1, 15, 10, 0, tzinfo=UTC)),
    ],
)
def test_one_calendar_month_clamps_to_the_end_of_a_shorter_month(filed, expected):
    assert reporting.add_one_month(filed) == expected


def test_an_incident_final_report_waits_for_the_notification():
    due = reporting.due_dates("incident", aware_at=AWARE, measure_available_at=None, notification_filed_at=None)

    assert due[Stage.FINAL_REPORT] is None


def test_next_due_is_the_first_stage_not_yet_filed():
    now = AWARE + timedelta(hours=2)

    nxt = reporting.next_due("vulnerability", AWARE, None, filed={}, now=now)

    assert (nxt.stage, nxt.due, nxt.overdue) == (Stage.EARLY_WARNING, AWARE + timedelta(hours=24), False)


def test_next_due_moves_on_once_a_stage_is_filed_and_reports_overdue():
    now = AWARE + timedelta(hours=80)

    nxt = reporting.next_due("vulnerability", AWARE, None, filed={Stage.EARLY_WARNING: AWARE}, now=now)

    assert nxt.stage == Stage.NOTIFICATION
    assert nxt.overdue is True


def test_next_due_has_no_date_for_a_final_report_before_the_fix():
    filed = {Stage.EARLY_WARNING: AWARE, Stage.NOTIFICATION: AWARE}

    nxt = reporting.next_due("vulnerability", AWARE, None, filed=filed, now=AWARE)

    assert (nxt.stage, nxt.due, nxt.overdue) == (Stage.FINAL_REPORT, None, False)


def test_nothing_is_due_once_the_final_report_is_filed():
    filed = {Stage.EARLY_WARNING: AWARE, Stage.NOTIFICATION: AWARE, Stage.FINAL_REPORT: AWARE}

    assert reporting.next_due("vulnerability", AWARE, None, filed=filed, now=AWARE) is None


def test_nothing_is_due_once_a_final_report_is_filed_ahead_of_the_earlier_stages():
    # A filed final report closes the report, so a stage skipped before it is not owed.
    filed = {Stage.FINAL_REPORT: AWARE}

    assert reporting.next_due("vulnerability", AWARE, None, filed=filed, now=AWARE) is None
    assert reporting.open_deadlines("vulnerability", AWARE, None, filed=filed) == []


def test_every_unfiled_stage_with_a_date_stays_open():
    # A missed early warning does not hide the notification due after it.
    open_stages = reporting.open_deadlines("vulnerability", AWARE, None, filed={})

    assert open_stages == [
        (Stage.EARLY_WARNING, AWARE + timedelta(hours=24)),
        (Stage.NOTIFICATION, AWARE + timedelta(hours=72)),
        (Stage.FINAL_REPORT, None),
    ]


def test_the_registry_keeps_each_kind_to_its_own_fields():
    vulnerability = {f.id for f in reporting.fields_for("vulnerability")}
    incident = {f.id for f in reporting.fields_for("incident")}

    assert "cve_id" in vulnerability and "cve_id" not in incident
    assert "suspected_unlawful" in incident and "suspected_unlawful" not in vulnerability
    assert {"title", "summary", "member_states"} <= vulnerability & incident


def test_the_registry_leaves_out_what_the_manufacturer_does_not_fill():
    ids = {f.id for f in reporting.SRP_FIELDS}

    assert not ids & {"manufacturer_name", "csirt_note"}


def _required(kind: str, stage: str) -> set[str]:
    return {f.id for f in reporting.required_fields(kind, stage)}


def test_each_stage_requires_what_glossary_1_6_requires_of_it():
    common_early = {"title", "summary", "member_states", "product_name", "product_version"}
    common_final = {"measures_taken", "measures_for_users"}

    assert _required("vulnerability", Stage.EARLY_WARNING) == common_early | {"vulnerability_aware_at"}
    assert _required("vulnerability", Stage.NOTIFICATION) == {"general_information"}
    assert _required("vulnerability", Stage.FINAL_REPORT) == common_final | {
        "measure_available_at",
        "measure_details",
        "vulnerability_severity",
        "vulnerability_impact",
    }
    assert _required("incident", Stage.EARLY_WARNING) == common_early | {"incident_aware_at", "suspected_unlawful"}
    assert _required("incident", Stage.NOTIFICATION) == {"incident_nature", "initial_assessment"}
    assert _required("incident", Stage.FINAL_REPORT) == common_final | {
        "incident_mitigation",
        "incident_severity",
        "incident_impact",
        "root_cause",
    }


def test_a_later_stage_does_not_ask_again_for_the_early_warning():
    for stage in (Stage.NOTIFICATION, Stage.FINAL_REPORT):
        on_form = {f.id for f in reporting.fields_for("vulnerability") if f.on_form(stage)}

        assert not on_form & {"title", "product_name", "member_states", "cve_id", "component_name"}


def test_an_intermediate_report_reads_as_the_final_report():
    assert _required("incident", Stage.INTERMEDIATE) == _required("incident", Stage.FINAL_REPORT)


def test_a_copied_field_is_on_the_form_without_being_required():
    occurred = reporting.FIELDS_BY_ID["vulnerability_occurred_at"]

    assert occurred.need_at(Stage.NOTIFICATION) == reporting.Need.COPIED
    assert occurred.on_form(Stage.NOTIFICATION)
    assert "vulnerability_occurred_at" not in _required("vulnerability", Stage.NOTIFICATION)


def test_additional_information_is_an_optional_early_warning_field():
    field = reporting.FIELDS_BY_ID["additional_information"]

    assert field.section == "common" and field.max_length == 255
    assert field.needs == (reporting.Need.OPTIONAL, reporting.Need.NOT_ASKED, reporting.Need.NOT_ASKED)


def test_missing_fields_names_only_the_empty_required_ones():
    values = {"title": "Router OS remote code execution", "summary": ""}

    missing = reporting.missing_fields("vulnerability", Stage.EARLY_WARNING, values)

    assert "summary" in missing and "title" not in missing


def test_a_value_longer_than_the_portal_allows_is_refused():
    errors = reporting.validate_values({"title": "x" * 256, "malicious_actor": "y" * 101})

    assert set(errors) == {"title", "malicious_actor"}


def test_an_unknown_field_is_refused():
    assert set(reporting.validate_values({"not_a_field": "x"})) == {"not_a_field"}
