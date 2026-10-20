"""CRA Article 14 reports: records, filings, permissions, pages, API and reminders."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.compliance import tasks
from sbomify.apps.compliance.forms import CRAFilingForm
from sbomify.apps.compliance.models import CRAReport, CRAReportFiling, CRAReportReminder
from sbomify.apps.compliance.reporting import Stage
from sbomify.apps.compliance.services import report_service
from sbomify.apps.core.authz import can
from sbomify.apps.core.models import Product, User
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.teams.models import Member, Workspace

AWARE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _ms(**delta: float) -> int:
    return int(timedelta(**delta).total_seconds() * 1000)


@pytest.fixture
def team(sample_team_with_owner_member):
    return sample_team_with_owner_member.team


@pytest.fixture
def owner(sample_user):
    return sample_user


@pytest.fixture
def product(team):
    return Product.objects.create(name="Router OS", team=team)


@pytest.fixture
def advisory(team, product):
    advisory = SecurityAdvisory.objects.create(
        team=team, title="Router OS remote code execution", summary="An attacker on the network can run code."
    )
    AdvisoryProduct.objects.create(advisory=advisory, product=product)
    AdvisoryVulnerability.objects.create(
        advisory=advisory,
        cve_id="CVE-2026-1234",
        exploitation_status=AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED,
    )
    return advisory


@pytest.fixture
def report(team, owner, product, advisory):
    result = report_service.create_report(
        team, owner, kind="vulnerability", product_id=product.id, advisory_id=advisory.id, aware_at=AWARE
    )
    assert result.ok, result.error
    return result.value


def _member(team: Workspace, role: str, name: str) -> User:
    user = User.objects.create_user(username=name, email=f"{name}@example.com", password="x")
    Member.objects.create(user=user, team=team, role=role)
    return user


def _client_for(team: Workspace, user: User) -> Client:
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


@pytest.mark.django_db
class TestCreateReport:
    def test_a_vulnerability_report_starts_from_the_advisory_and_the_product(self, report):
        values = report.srp_fields

        assert values["title"] == "Router OS remote code execution"
        assert values["summary"] == "An attacker on the network can run code."
        assert values["cve_id"] == "CVE-2026-1234"
        assert values["product_name"] == "Router OS"

    def test_a_vulnerability_report_needs_an_advisory_that_names_the_product(self, team, owner, advisory):
        other = Product.objects.create(name="Switch OS", team=team)

        result = report_service.create_report(
            team, owner, kind="vulnerability", product_id=other.id, advisory_id=advisory.id, aware_at=AWARE
        )

        assert not result.ok and result.status_code == 400

    def test_one_report_per_advisory_and_product(self, team, owner, product, advisory, report):
        result = report_service.create_report(
            team, owner, kind="vulnerability", product_id=product.id, advisory_id=advisory.id, aware_at=AWARE
        )

        assert not result.ok and result.status_code == 409

    def test_an_incident_report_needs_no_advisory(self, team, owner, product):
        result = report_service.create_report(team, owner, kind="incident", product_id=product.id, aware_at=AWARE)

        assert result.ok
        assert result.value.advisory is None

    def test_another_workspaces_product_reads_as_absent(self, team, owner):
        foreign = Product.objects.create(name="Elsewhere", team=Workspace.objects.create(name="Other"))

        result = report_service.create_report(team, owner, kind="incident", product_id=foreign.id, aware_at=AWARE)

        assert not result.ok and result.status_code == 404


@pytest.mark.django_db
class TestFilings:
    def test_a_filing_keeps_what_was_filed_and_lands_on_the_advisory_timeline(self, report, owner):
        result = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, srp_reference="SRP-1")

        assert result.ok
        assert result.value.snapshot["srp_fields"]["title"] == "Router OS remote code execution"
        event = AdvisoryEvent.objects.get(advisory=report.advisory, event_type="cra_early_warning")
        assert event.payload["srp_reference"] == "SRP-1"

    def test_a_stage_is_filed_once_but_intermediate_reports_repeat(self, report, owner):
        assert report_service.record_filing(report, owner, stage=Stage.NOTIFICATION, srp_reference="A").ok

        again = report_service.record_filing(report, owner, stage=Stage.NOTIFICATION, srp_reference="B")

        assert not again.ok and again.status_code == 409
        assert report_service.record_filing(report, owner, stage=Stage.INTERMEDIATE, srp_reference="C").ok
        assert report_service.record_filing(report, owner, stage=Stage.INTERMEDIATE, srp_reference="D").ok

    def test_filings_are_append_only(self, report, owner):
        filing = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, srp_reference="A").value

        filing.srp_reference = "changed"
        with pytest.raises(ValidationError):
            filing.save()
        with pytest.raises(ValidationError):
            filing.delete()
        with pytest.raises(ValidationError):
            CRAReportFiling.objects.filter(pk=filing.pk).update(srp_reference="changed")
        with pytest.raises(ValidationError):
            CRAReportFiling.objects.filter(pk=filing.pk).delete()

    def test_a_report_with_a_filing_cannot_be_deleted(self, report, owner):
        report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, srp_reference="A")

        result = report_service.delete_report(report, owner)

        assert not result.ok and result.status_code == 409
        assert CRAReport.objects.filter(pk=report.pk).exists()

    def test_a_report_with_no_filing_can_be_deleted(self, report, owner):
        assert report_service.delete_report(report, owner).ok
        assert not CRAReport.objects.filter(pk=report.pk).exists()

    def test_the_report_is_read_only_once_the_final_report_is_filed(self, report, owner):
        report_service.record_filing(report, owner, stage=Stage.FINAL_REPORT, srp_reference="F")

        result = report_service.update_report(report, owner, values={"title": "New title"})

        assert not result.ok and result.status_code == 409

    def test_an_over_long_value_is_refused(self, report, owner):
        result = report_service.update_report(report, owner, values={"title": "x" * 256})

        assert not result.ok and result.status_code == 400

    def test_the_copy_view_marks_what_the_stage_still_needs(self, report):
        rows = {row["id"]: row for row in report_service.srp_layout(report, Stage.NOTIFICATION)}

        assert rows["title"]["missing"] is False
        assert rows["general_information"]["missing"] is True
        assert "suspected_unlawful" not in rows


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "manage", "read"),
    [
        ("owner", True, True),
        ("admin", True, True),
        ("member", False, True),
        ("operator", False, True),
        ("guest", False, False),
    ],
)
def test_who_may_file_and_who_may_read(team, report, role, manage, read):
    user = _member(team, role, f"user_{role}")

    assert bool(can(user, "cra_report:manage", report)) is manage
    assert bool(can(user, "cra_report:read", report)) is read


@pytest.mark.django_db
class TestApi:
    def test_an_admin_files_through_the_api(self, team, owner, product, advisory):
        client = _client_for(team, owner)

        created = client.post(
            "/api/v1/compliance/cra-reports",
            data=json.dumps(
                {
                    "kind": "vulnerability",
                    "product_id": product.id,
                    "advisory_id": advisory.id,
                    "aware_at": AWARE.isoformat(),
                }
            ),
            content_type="application/json",
        )
        assert created.status_code == 201, created.content
        report_id = created.json()["id"]

        patched = client.patch(
            f"/api/v1/compliance/cra-reports/{report_id}",
            data=json.dumps({"values": {"general_information": "Exploited in the wild."}}),
            content_type="application/json",
        )
        assert patched.status_code == 200
        filed = client.post(
            f"/api/v1/compliance/cra-reports/{report_id}/filings",
            data=json.dumps({"stage": "early_warning", "srp_reference": "SRP-9"}),
            content_type="application/json",
        )
        assert filed.status_code == 201
        srp = client.get(f"/api/v1/compliance/cra-reports/{report_id}/srp?stage=notification")
        assert srp.status_code == 200
        fields = {row["id"]: row for row in srp.json()["fields"]}
        assert fields["general_information"]["value"] == "Exploited in the wild."
        listed = client.get("/api/v1/compliance/cra-reports")
        assert [item["id"] for item in listed.json()] == [report_id]
        assert listed.json()[0]["next_due"]["stage"] == "notification"

    def test_a_member_reads_but_cannot_file(self, team, report):
        client = _client_for(team, _member(team, "member", "reader"))

        assert client.get(f"/api/v1/compliance/cra-reports/{report.id}").status_code == 200
        refused = client.post(
            f"/api/v1/compliance/cra-reports/{report.id}/filings",
            data=json.dumps({"stage": "early_warning", "srp_reference": "X"}),
            content_type="application/json",
        )
        assert refused.status_code == 403

    def test_another_workspaces_report_reads_as_absent(self, report):
        stranger_team = Workspace.objects.create(name="Elsewhere")
        client = _client_for(stranger_team, _member(stranger_team, "owner", "stranger"))

        assert client.get(f"/api/v1/compliance/cra-reports/{report.id}").status_code == 404


@pytest.mark.django_db
class TestPages:
    def test_an_admin_sees_the_list_and_can_record_a_filing(self, team, owner, report):
        client = _client_for(team, owner)

        listing = client.get(reverse("compliance:cra_reports"))
        detail = client.get(reverse("compliance:cra_report_detail", args=[report.id]))

        assert listing.status_code == 200 and "Router OS" in listing.content.decode()
        assert detail.status_code == 200 and "Record filing" in detail.content.decode()

    def test_recording_a_filing_from_the_page(self, team, owner, report):
        client = _client_for(team, owner)

        response = client.post(
            reverse("compliance:cra_report_detail", args=[report.id]),
            {"action": "file", "stage": "early_warning", "srp_reference": "SRP-77", "filed_at": ""},
        )

        assert response.status_code == 302
        assert report.filings.get().srp_reference == "SRP-77"

    def test_a_member_reads_the_report_without_the_forms(self, team, report):
        client = _client_for(team, _member(team, "member", "reader"))

        detail = client.get(reverse("compliance:cra_report_detail", args=[report.id]))

        assert detail.status_code == 200
        assert "Record filing" not in detail.content.decode()

    def test_a_guest_is_kept_out(self, team, report):
        client = _client_for(team, _member(team, "guest", "visitor"))

        response = client.get(reverse("compliance:cra_report_detail", args=[report.id]))

        assert response.status_code in (302, 403, 404)

    def test_the_advisory_page_offers_a_report_for_an_exploited_vulnerability(self, team, owner, advisory):
        client = _client_for(team, owner)

        page = client.get(reverse("core:security_advisory_detail", args=[advisory.id]))

        assert "Start a CRA report" in page.content.decode()

    def test_starting_a_report_from_the_advisory(self, team, owner, product, advisory):
        client = _client_for(team, owner)

        response = client.post(
            reverse("compliance:cra_report_create"),
            {"kind": "vulnerability", "product_id": product.id, "advisory_id": advisory.id},
        )

        report = CRAReport.objects.get(advisory=advisory, product=product)
        assert response.status_code == 302
        assert response.url == reverse("compliance:cra_report_detail", args=[report.id])


@pytest.mark.django_db
class TestReminders:
    def test_a_reminder_is_sent_once_even_when_its_message_arrives_twice(self, report):
        due = AWARE + timedelta(hours=24)

        tasks.send_due_reminders(now=due - timedelta(hours=5))
        tasks.send_due_reminders(now=due - timedelta(hours=5))

        assert len(mail.outbox) == 1
        assert CRAReportReminder.objects.filter(report=report, stage=Stage.EARLY_WARNING).count() == 1

    def test_no_reminder_for_a_stage_already_filed(self, report, owner):
        report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, srp_reference="A")

        tasks.send_due_reminders(now=AWARE + timedelta(hours=23))

        assert mail.outbox == []

    def test_reminders_go_to_owners_and_admins_only(self, team, report):
        _member(team, "admin", "boss")
        _member(team, "member", "worker")

        tasks.send_due_reminders(now=AWARE + timedelta(hours=23))

        recipients = sorted(message.to[0] for message in mail.outbox)
        assert "boss@example.com" in recipients
        assert "worker@example.com" not in recipients

    def test_scheduling_queues_a_message_before_and_at_every_open_deadline(self, report):
        # The final report has no date until a fix exists, so it queues nothing yet.
        now = AWARE + timedelta(hours=1)
        with patch.object(tasks.send_cra_report_reminders, "send_with_options") as send:
            tasks.schedule_reminders(report, now=now)

        delays = sorted(call.kwargs["delay"] for call in send.call_args_list)
        assert delays == [_ms(hours=17), _ms(hours=23), _ms(hours=65), _ms(hours=71)]

    def test_a_missed_early_warning_still_brings_the_notification_reminder(self, report):
        tasks.send_due_reminders(now=AWARE + timedelta(hours=67))

        subjects = [message.subject for message in mail.outbox]
        assert any("notification" in subject for subject in subjects), subjects
        assert any("early warning" in subject for subject in subjects), subjects

    def test_scheduling_reads_the_filing_just_recorded(self, team, owner, product, django_capture_on_commit_callbacks):
        aware = timezone.now() - timedelta(hours=1)
        created = report_service.create_report(team, owner, kind="incident", product_id=product.id, aware_at=aware)
        fetched = report_service.get_report(team, created.value.pk)
        list(fetched.filings.all())  # the prefetch the page and the API already hold

        with patch.object(tasks.send_cra_report_reminders, "send_with_options") as send:
            with django_capture_on_commit_callbacks(execute=True):
                report_service.record_filing(fetched, owner, stage=Stage.EARLY_WARNING, srp_reference="A")

        # Only the notification is still open, 72 hours after becoming aware.
        delays = sorted(call.kwargs["delay"] for call in send.call_args_list)
        assert len(delays) == 2, delays
        assert abs(delays[0] - _ms(hours=65)) < _ms(minutes=1)
        assert abs(delays[1] - _ms(hours=71)) < _ms(minutes=1)


@pytest.mark.django_db
class TestReminderDelivery:
    def test_a_failed_send_is_retried_without_mailing_whoever_got_it(self, team, report):
        _member(team, "admin", "boss")
        original = tasks.EmailMultiAlternatives.send
        failing = {"boss@example.com"}

        def send(self, *args, **kwargs):
            if self.to[0] in failing:
                raise ConnectionError("mail server down")
            return original(self, *args, **kwargs)

        now = AWARE + timedelta(hours=19)
        with patch.object(tasks.EmailMultiAlternatives, "send", send):
            with pytest.raises(tasks.ReminderDeliveryFailed):
                tasks.send_due_reminders(now=now)
        assert [message.to for message in mail.outbox] == [[report.created_by.email]]

        failing.clear()
        with patch.object(tasks.EmailMultiAlternatives, "send", send):
            tasks.send_due_reminders(now=now)

        assert sorted(message.to[0] for message in mail.outbox) == sorted([report.created_by.email, "boss@example.com"])

    def test_a_reminder_another_worker_is_sending_is_left_to_it(self, report):
        now = AWARE + timedelta(hours=19)
        CRAReportReminder.objects.create(
            report=report,
            stage=Stage.EARLY_WARNING,
            threshold="soon",
            recipient=report.created_by.email,
            claimed_at=now,
        )

        tasks.send_due_reminders(now=now)

        assert mail.outbox == []

    def test_a_claim_left_by_a_worker_that_died_is_taken_over(self, report):
        now = AWARE + timedelta(hours=19)
        CRAReportReminder.objects.create(
            report=report,
            stage=Stage.EARLY_WARNING,
            threshold="soon",
            recipient=report.created_by.email,
            claimed_at=now - timedelta(hours=1),
        )

        tasks.send_due_reminders(now=now)

        assert [message.to for message in mail.outbox] == [[report.created_by.email]]
        assert CRAReportReminder.objects.get(report=report, threshold="soon").sent_at is not None


@pytest.mark.django_db
class TestStaleReports:
    """A report fetched before another request wrote to it, as two concurrent requests would."""

    @staticmethod
    def _stale(team, report):
        fetched = report_service.get_report(team, report.pk)
        list(fetched.filings.all())
        return fetched

    def test_a_report_filed_after_it_was_fetched_is_not_deleted(self, team, owner, report):
        stale = self._stale(team, report)
        report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, srp_reference="A")

        result = report_service.delete_report(stale, owner)

        assert result.status_code == 409
        assert CRAReport.objects.filter(pk=report.pk).exists()

    def test_a_report_closed_after_it_was_fetched_is_not_edited(self, team, owner, report):
        stale = self._stale(team, report)
        report_service.record_filing(report, owner, stage=Stage.FINAL_REPORT, srp_reference="F")

        result = report_service.update_report(stale, owner, values={"general_information": "Late edit."})

        assert result.status_code == 409
        report.refresh_from_db()
        assert "general_information" not in report.srp_fields

    def test_a_report_closed_after_it_was_fetched_takes_no_more_stages(self, team, owner, report):
        stale = self._stale(team, report)
        report_service.record_filing(report, owner, stage=Stage.FINAL_REPORT, srp_reference="F")

        result = report_service.record_filing(stale, owner, stage=Stage.NOTIFICATION, srp_reference="N")

        assert result.status_code == 409
        assert not CRAReportFiling.objects.filter(report=report, stage=Stage.NOTIFICATION).exists()

    @pytest.mark.parametrize("action", ["update", "file", "delete"])
    def test_each_write_locks_the_report_row(self, team, owner, report, action):
        calls = {
            "update": lambda: report_service.update_report(report, owner, values={"title": "T"}),
            "file": lambda: report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING),
            "delete": lambda: report_service.delete_report(report, owner),
        }
        with CaptureQueriesContext(connection) as queries:
            calls[action]()

        assert any("compliance_cra_reports" in q["sql"] and "FOR UPDATE" in q["sql"] for q in queries.captured_queries)


@pytest.mark.django_db
class TestTimestamps:
    """A time without a zone cannot be compared with the deadlines, so the API refuses it."""

    def test_creating_with_a_naive_time_is_refused(self, team, owner, product, advisory):
        client = _client_for(team, owner)

        response = client.post(
            "/api/v1/compliance/cra-reports",
            data=json.dumps(
                {
                    "kind": "vulnerability",
                    "product_id": product.id,
                    "advisory_id": advisory.id,
                    "aware_at": "2026-10-01T09:00:00",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 422, response.content
        assert not CRAReport.objects.exists()

    def test_editing_with_a_naive_time_is_refused(self, team, owner, report):
        client = _client_for(team, owner)

        response = client.patch(
            f"/api/v1/compliance/cra-reports/{report.pk}",
            data=json.dumps({"measure_available_at": "2026-10-03T09:00:00"}),
            content_type="application/json",
        )

        assert response.status_code == 422, response.content
        report.refresh_from_db()
        assert report.measure_available_at is None

    def test_filing_with_a_naive_time_is_refused(self, team, owner, report):
        client = _client_for(team, owner)

        response = client.post(
            f"/api/v1/compliance/cra-reports/{report.pk}/filings",
            data=json.dumps({"stage": "early_warning", "filed_at": "2026-10-01T12:00:00"}),
            content_type="application/json",
        )

        assert response.status_code == 422, response.content
        assert not report.filings.exists()

    def test_an_aware_time_is_accepted(self, team, owner, report):
        client = _client_for(team, owner)

        response = client.patch(
            f"/api/v1/compliance/cra-reports/{report.pk}",
            data=json.dumps({"measure_available_at": "2026-10-03T09:00:00+02:00"}),
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        report.refresh_from_db()
        assert report.measure_available_at == datetime(2026, 10, 3, 7, 0, tzinfo=UTC)

    def test_the_page_forms_read_times_as_utc(self):
        form = CRAFilingForm(data={"stage": "early_warning", "filed_at": "2026-10-01T12:00"})

        assert form.is_valid(), form.errors
        assert form.cleaned_data["filed_at"] == datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.mark.django_db
class TestBell:
    def _request(self, team, user):
        request = RequestFactory().get("/")
        request.user = user
        request.session = {"current_workspace": {"key": team.key, "id": team.id}}
        return request

    def test_an_admin_sees_the_next_deadline(self, team, owner, report):
        from sbomify.apps.compliance.notifications import get_notifications

        with patch("sbomify.apps.compliance.notifications.timezone.now", return_value=AWARE + timedelta(hours=20)):
            notes = get_notifications(self._request(team, owner))

        assert len(notes) == 1
        assert "Early warning" in notes[0].message and "Router OS" in notes[0].message

    def test_a_member_sees_no_deadline(self, team, report):
        from sbomify.apps.compliance.notifications import get_notifications

        member = _member(team, "member", "reader")
        with patch("sbomify.apps.compliance.notifications.timezone.now", return_value=AWARE + timedelta(hours=20)):
            assert get_notifications(self._request(team, member)) == []


def test_the_export_points_operators_at_the_in_app_tracker():
    from sbomify.apps.compliance.services.export_service import _article_14_reporting_readme

    assert "CRA reports" in _article_14_reporting_readme()
