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

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
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
    AdvisoryProductStatus,
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

    def test_an_incident_from_an_advisory_takes_only_incident_fields(self, team, owner, product, advisory):
        # The advisory's vulnerability carries a CVE id, which the incident form has
        # no field for. Prefilling it made the values the API hands back fail PATCH.
        client = _client_for(team, owner)
        created = client.post(
            "/api/v1/compliance/cra-reports",
            data=json.dumps(
                {
                    "kind": "incident",
                    "product_id": product.id,
                    "advisory_id": advisory.id,
                    "aware_at": AWARE.isoformat(),
                }
            ),
            content_type="application/json",
        )
        assert created.status_code == 201, created.content
        report_id = created.json()["id"]
        values = client.get(f"/api/v1/compliance/cra-reports/{report_id}").json()["values"]
        assert "cve_id" not in values
        assert values["title"] == advisory.title

        patched = client.patch(
            f"/api/v1/compliance/cra-reports/{report_id}",
            data=json.dumps({"values": values}),
            content_type="application/json",
        )

        assert patched.status_code == 200, patched.content


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
            data=json.dumps(
                {"stage": "early_warning", "srp_reference": "SRP-9", "revision": patched.json()["revision"]}
            ),
            content_type="application/json",
        )
        assert filed.status_code == 201
        assert filed.json()["filed_by"] == owner.email
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
            data=json.dumps(
                {"stage": "early_warning", "srp_reference": "X", "revision": report.revision}
            ),
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
            {
                "action": "file",
                "stage": "early_warning",
                "srp_reference": "SRP-77",
                "filed_at": "",
                "revision": report.revision,
            },
        )

        assert response.status_code == 302
        assert report.filings.get().srp_reference == "SRP-77"

    def test_saving_the_page_keeps_the_seconds_the_form_does_not_show(self, team, owner, product):
        # The date inputs show minutes, so a time saved with seconds comes back
        # without them. That is not an edit, and must not move the deadlines.
        aware = AWARE + timedelta(seconds=37)
        created = report_service.create_report(team, owner, kind="incident", product_id=product.id, aware_at=aware)
        report = created.value
        client = _client_for(team, owner)

        with patch.object(report_service, "log_cra_report_event") as audit:
            response = client.post(
                reverse("compliance:cra_report_detail", args=[report.id]),
                {**report.srp_fields, "action": "save", "aware_at": "2026-10-01T09:00", "occurred_at": ""},
            )

        assert response.status_code == 302
        report.refresh_from_db()
        assert report.aware_at == aware
        assert not audit.called

    def test_saving_the_page_with_a_new_minute_changes_the_time(self, team, owner, product):
        created = report_service.create_report(
            team, owner, kind="incident", product_id=product.id, aware_at=AWARE + timedelta(seconds=37)
        )
        report = created.value
        client = _client_for(team, owner)

        client.post(
            reverse("compliance:cra_report_detail", args=[report.id]),
            {**report.srp_fields, "action": "save", "aware_at": "2026-10-01T09:05", "occurred_at": ""},
        )

        report.refresh_from_db()
        assert report.aware_at == AWARE + timedelta(minutes=5)

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

    def test_a_deleted_account_gets_no_reminder(self, team, report):
        # Deleting an account in a shared workspace keeps its membership and disables the user.
        former = _member(team, "admin", "former")
        former.is_active = False
        former.deleted_at = timezone.now()
        former.save(update_fields=["is_active", "deleted_at"])

        tasks.send_due_reminders(now=AWARE + timedelta(hours=23))

        recipients = {message.to[0] for message in mail.outbox}
        assert recipients, "the owner should still be reminded"
        assert "former@example.com" not in recipients

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
            due=AWARE + timedelta(hours=24),
            threshold="soon",
            recipient=report.created_by.email,
            claimed_at=now,
        )

        tasks.send_due_reminders(now=now)

        assert mail.outbox == []

    def test_while_another_worker_sends_the_soon_reminder_the_due_one_waits(self, report):
        # Both thresholds have passed. Another worker holds "soon" and is mailing
        # this person; claiming "due" beside it would send them the same email twice.
        due = AWARE + timedelta(hours=24)
        now = due + timedelta(minutes=5)
        CRAReportReminder.objects.create(
            report=report,
            stage=Stage.EARLY_WARNING,
            due=due,
            threshold="soon",
            recipient=report.created_by.email,
            claimed_at=now - timedelta(minutes=1),
        )

        with patch.object(tasks.send_cra_report_reminders, "send_with_options") as send:
            tasks.send_due_reminders(report_id=report.pk, now=now)

        assert mail.outbox == []
        assert not CRAReportReminder.objects.filter(report=report, threshold="due", claimed_at__isnull=False).exists()
        send.assert_called_once()

        # The holder never finished: once its claim expires, one email covers both.
        tasks.send_due_reminders(report_id=report.pk, now=now + tasks.CLAIM_TIMEOUT)

        assert [message.to for message in mail.outbox] == [[report.created_by.email]]
        assert CRAReportReminder.objects.filter(report=report, sent_at__isnull=False).count() == 2

    def test_a_claim_left_by_a_worker_that_died_is_taken_over(self, report):
        now = AWARE + timedelta(hours=19)
        CRAReportReminder.objects.create(
            report=report,
            stage=Stage.EARLY_WARNING,
            due=AWARE + timedelta(hours=24),
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
class TestSrpStage:
    def test_an_unknown_stage_is_refused(self, team, owner, report):
        client = _client_for(team, owner)

        response = client.get(f"/api/v1/compliance/cra-reports/{report.pk}/srp?stage=foo")

        assert response.status_code == 400, response.content

    @pytest.mark.parametrize("stage", ["early_warning", "notification", "final_report"])
    def test_each_deadline_stage_lays_out(self, team, owner, report, stage):
        client = _client_for(team, owner)

        response = client.get(f"/api/v1/compliance/cra-reports/{report.pk}/srp?stage={stage}")

        assert response.status_code == 200
        assert response.json()["stage"] == stage


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
        form = CRAFilingForm(data={"stage": "early_warning", "filed_at": "2026-10-01T12:00", "revision": "r1"})

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


@pytest.mark.django_db
class TestCorrectedDeadline:
    def test_a_corrected_deadline_gets_its_own_reminders(self, report, owner):
        tasks.send_due_reminders(now=AWARE + timedelta(hours=24))
        assert len(mail.outbox) == 1

        result = report_service.update_report(report, owner, dates={"aware_at": AWARE + timedelta(hours=5)})
        assert result.ok, result.error
        tasks.send_due_reminders(now=AWARE + timedelta(hours=29))

        assert len(mail.outbox) == 2


@pytest.mark.django_db
class TestPendingClaim:
    def test_a_claim_still_held_brings_another_attempt_when_it_expires(self, report):
        now = AWARE + timedelta(hours=19)
        CRAReportReminder.objects.create(
            report=report,
            stage=Stage.EARLY_WARNING,
            due=AWARE + timedelta(hours=24),
            threshold="soon",
            recipient=report.created_by.email,
            claimed_at=now - timedelta(minutes=1),
        )

        with patch.object(tasks.send_cra_report_reminders, "send_with_options") as send:
            tasks.send_due_reminders(report_id=report.pk, now=now)

        assert mail.outbox == []
        send.assert_called_once()
        assert send.call_args.kwargs["args"] == (report.pk,)
        assert send.call_args.kwargs["delay"] >= _ms(minutes=9)

        tasks.send_due_reminders(report_id=report.pk, now=now + tasks.CLAIM_TIMEOUT)

        assert [message.to for message in mail.outbox] == [[report.created_by.email]]


@pytest.fixture
def two_products(team, product):
    other = Product.objects.create(name="Gateway", team=team)
    advisory = SecurityAdvisory.objects.create(
        team=team, title="Shared library flaw", summary="One flaw, two products."
    )
    router = AdvisoryProduct.objects.create(advisory=advisory, product=product)
    AdvisoryProduct.objects.create(advisory=advisory, product=other)
    critical = AdvisoryVulnerability.objects.create(
        advisory=advisory,
        cve_id="CVE-2026-1111",
        severity="critical",
        description="Only the gateway ships this.",
        exploitation_status=AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED,
    )
    AdvisoryVulnerability.objects.create(
        advisory=advisory,
        cve_id="CVE-2026-2222",
        severity="high",
        description="Both ship this.",
        exploitation_status=AdvisoryVulnerability.ExploitationStatus.KNOWN_EXPLOITED,
    )
    AdvisoryProductStatus.objects.create(
        vulnerability=critical, advisory_product=router, status=AdvisoryProductStatus.Status.NOT_AFFECTED
    )
    return advisory, product, other


@pytest.mark.django_db
class TestProductStatus:
    def test_the_prefill_skips_a_vulnerability_the_product_is_not_affected_by(self, team, owner, two_products):
        advisory, router, gateway = two_products

        for product, cve in ((router, "CVE-2026-2222"), (gateway, "CVE-2026-1111")):
            result = report_service.create_report(
                team, owner, kind="vulnerability", product_id=product.id, advisory_id=advisory.id, aware_at=AWARE
            )
            assert result.ok, result.error
            assert result.value.srp_fields["cve_id"] == cve

    def test_no_report_is_offered_for_a_product_nothing_exploited_affects(self, team, owner, two_products):
        advisory, router, gateway = two_products
        AdvisoryProductStatus.objects.create(
            vulnerability=advisory.vulnerabilities.get(cve_id="CVE-2026-2222"),
            advisory_product=advisory.products.get(product=router),
            status=AdvisoryProductStatus.Status.FALSE_POSITIVE,
        )

        rows = {row["product_name"]: row for row in report_service.advisory_reporting(team, advisory.pk)["rows"]}
        refused = report_service.create_report(
            team, owner, kind="vulnerability", product_id=router.id, advisory_id=advisory.id, aware_at=AWARE
        )

        assert rows["Router OS"]["can_start"] is False
        assert rows["Gateway"]["can_start"] is True
        assert refused.status_code == 400


@pytest.mark.django_db
class TestClosedReportForm:
    def _close(self, report, owner):
        for stage in (Stage.EARLY_WARNING, Stage.NOTIFICATION, Stage.FINAL_REPORT):
            assert report_service.record_filing(report, owner, stage=stage).ok

    def test_a_closed_report_offers_only_users_informed(self, team, owner, report):
        self._close(report, owner)

        page = _client_for(team, owner).get(reverse("compliance:cra_report_detail", args=[report.id]))

        assert [s["value"] for s in page.context["filing_stages"]] == [Stage.USERS_INFORMED]
        assert "Record filing" in page.content.decode()

    def test_the_form_goes_once_nothing_is_left_to_file(self, team, owner, report):
        self._close(report, owner)
        assert report_service.record_filing(report, owner, stage=Stage.USERS_INFORMED).ok

        page = _client_for(team, owner).get(reverse("compliance:cra_report_detail", args=[report.id]))

        assert page.context["filing_stages"] == []
        assert "Record filing" not in page.content.decode()


def _bell_request(team, user):
    request = RequestFactory().get("/")
    request.user = user
    request.session = {"current_workspace": {"key": team.key, "id": team.id}}
    return request


@pytest.mark.django_db
class TestCorrectedDeadlineBell:
    def test_a_dismissed_alert_does_not_hide_the_corrected_deadline(self, team, owner, report):
        from sbomify.apps.compliance.notifications import get_notifications

        with patch("sbomify.apps.compliance.notifications.timezone.now", return_value=AWARE + timedelta(hours=20)):
            before = get_notifications(_bell_request(team, owner))
        assert report_service.update_report(report, owner, dates={"aware_at": AWARE - timedelta(hours=2)}).ok
        with patch("sbomify.apps.compliance.notifications.timezone.now", return_value=AWARE + timedelta(hours=20)):
            after = get_notifications(_bell_request(team, owner))

        assert len(before) == len(after) == 1
        assert before[0].id != after[0].id


@pytest.mark.django_db
class TestFilingEvents:
    def test_each_intermediate_report_lands_on_the_timeline(self, report, owner):
        for reference in ("SRP-C", "SRP-D"):
            assert report_service.record_filing(report, owner, stage=Stage.INTERMEDIATE, srp_reference=reference).ok

        events = AdvisoryEvent.objects.filter(advisory=report.advisory, event_type="cra_intermediate_report")
        assert [event.payload["srp_reference"] for event in events.order_by("created_at")] == ["SRP-C", "SRP-D"]

    def test_a_filing_event_says_what_was_filed_for_which_product(self, report, owner):
        filed_at = datetime(2026, 10, 2, 8, 30, tzinfo=UTC)
        assert report_service.record_filing(
            report, owner, stage=Stage.NOTIFICATION, srp_reference="SRP-9", filed_at=filed_at
        ).ok

        event = AdvisoryEvent.objects.get(advisory=report.advisory, event_type="cra_notification")
        assert "Router OS" in event.body
        assert "SRP-9" in event.body
        assert "02 Oct 2026 08:30" in event.body


@pytest.mark.django_db
class TestBrokerDown:
    def test_a_saved_filing_survives_a_broker_failure_and_is_scheduled_later(
        self, team, owner, report, django_capture_on_commit_callbacks
    ):
        from sbomify.apps.compliance.notifications import get_notifications

        with patch.object(tasks.send_cra_report_reminders, "send_with_options", side_effect=ConnectionError("down")):
            with django_capture_on_commit_callbacks(execute=True):
                result = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, srp_reference="A")

        assert result.ok
        report.refresh_from_db()
        assert report.reminders_pending is True

        # The next owner or admin page view is the dispatcher production has.
        with patch.object(tasks.send_cra_report_reminders, "send_with_options") as send:
            get_notifications(_bell_request(team, owner))

        assert send.called
        report.refresh_from_db()
        assert report.reminders_pending is False


@pytest.mark.django_db
class TestAdvisoryCardQueries:
    def test_the_card_costs_the_same_queries_however_many_products(self, team, two_products):
        advisory, _router, _gateway = two_products
        with CaptureQueriesContext(connection) as two:
            report_service.advisory_reporting(team, advisory.pk)
        for number in range(3):
            extra = Product.objects.create(name=f"Extra {number}", team=team)
            AdvisoryProduct.objects.create(advisory=advisory, product=extra)
        with CaptureQueriesContext(connection) as five:
            rows = report_service.advisory_reporting(team, advisory.pk)["rows"]

        assert len(rows) == 5
        assert len(five.captured_queries) == len(two.captured_queries)


def _incident_only_field() -> str:
    from sbomify.apps.compliance.reporting import SRP_FIELDS

    return next(field.id for field in SRP_FIELDS if field.section == "incident" and not field.column)


@pytest.mark.django_db
class TestFieldsOfTheOtherKind:
    def test_a_field_of_the_other_kind_is_refused(self, report, owner):
        key = _incident_only_field()

        result = report_service.update_report(report, owner, values={key: "Ransomware on the update server."})

        assert not result.ok and result.status_code == 400
        report.refresh_from_db()
        assert key not in report.srp_fields

    def test_the_api_refuses_it_too(self, team, owner, report):
        response = _client_for(team, owner).patch(
            f"/api/v1/compliance/cra-reports/{report.pk}",
            data=json.dumps({"values": {_incident_only_field(): "x"}}),
            content_type="application/json",
        )

        assert response.status_code == 400, response.content


@pytest.mark.django_db
class TestSrpReferenceLength:
    def test_the_api_refuses_a_reference_the_portal_cannot_have_given(self, team, owner, report):
        response = _client_for(team, owner).post(
            f"/api/v1/compliance/cra-reports/{report.pk}/filings",
            data=json.dumps({"stage": "early_warning", "srp_reference": "S" * 101}),
            content_type="application/json",
        )

        assert response.status_code in (400, 422), response.content
        assert not report.filings.exists()

    def test_the_service_refuses_rather_than_truncates(self, report, owner):
        result = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, srp_reference="S" * 101)

        assert not result.ok and result.status_code == 400
        assert not report.filings.exists()

    def test_a_reference_of_a_hundred_characters_is_kept_whole(self, report, owner):
        result = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, srp_reference="S" * 100)

        assert result.ok and result.value.srp_reference == "S" * 100


@pytest.mark.django_db
class TestHeaderMenuOnReportPages:
    def test_the_report_pages_leave_the_workspace_wide_can_manage_alone(self, team, report):
        # can_manage is the context processor's MANAGE flag, which the header's
        # New menu reads. The report pages name their own flag, so a member keeps
        # the menu and any template that reads can_manage gets the workspace value.
        client = _client_for(team, _member(team, "member", "contributor"))

        for url in (reverse("compliance:cra_reports"), reverse("compliance:cra_report_detail", args=[report.id])):
            response = client.get(url)
            assert response.context["can_manage"] is True, url
            assert response.context["can_manage_cra_reports"] is False, url
            assert 'aria-label="Create new item"' in response.content.decode(), url
        detail = client.get(reverse("compliance:cra_report_detail", args=[report.id])).content.decode()
        assert "Record filing" not in detail

    def test_an_admin_still_gets_the_report_controls(self, team, owner, report):
        detail = _client_for(team, owner).get(reverse("compliance:cra_report_detail", args=[report.id]))

        assert "Record filing" in detail.content.decode()


@pytest.mark.django_db
class TestPendingMark:
    def test_a_write_that_marks_the_report_during_a_dispatch_keeps_its_mark(self, report):
        CRAReport.objects.filter(pk=report.pk).update(reminders_pending=True)

        def newer_write_marks_again(_report):
            # A write that lands while this dispatch is scheduling, and whose own
            # queueing then fails, leaves its mark for the next dispatch.
            CRAReport.objects.filter(pk=report.pk).update(reminders_pending=True)

        with patch.object(tasks, "schedule_reminders", side_effect=newer_write_marks_again):
            tasks.dispatch_pending_reminders()

        report.refresh_from_db()
        assert report.reminders_pending is True

    def test_a_failed_dispatch_keeps_the_mark(self, report):
        CRAReport.objects.filter(pk=report.pk).update(reminders_pending=True)

        with patch.object(tasks, "schedule_reminders", side_effect=ConnectionError("down")):
            assert tasks.dispatch_pending_reminders() == 0

        report.refresh_from_db()
        assert report.reminders_pending is True

    def test_a_reload_that_fails_keeps_the_mark(self, report):
        from django.db import DatabaseError

        CRAReport.objects.filter(pk=report.pk).update(reminders_pending=True)

        with patch.object(CRAReport.objects, "prefetch_related", side_effect=DatabaseError("connection lost")):
            assert tasks.dispatch_pending_reminders() == 0

        report.refresh_from_db()
        assert report.reminders_pending is True

    def test_a_dispatch_interrupted_after_the_claim_keeps_the_mark(self, report):
        class Interrupted(BaseException):
            """What a worker killed mid-dispatch looks like to the code it was running."""

        CRAReport.objects.filter(pk=report.pk).update(reminders_pending=True)

        with patch.object(tasks, "schedule_reminders", side_effect=Interrupted):
            with pytest.raises(Interrupted):
                tasks.dispatch_pending_reminders()

        report.refresh_from_db()
        assert report.reminders_pending is True


@pytest.mark.django_db
class TestDispatchCooldown:
    def test_a_broker_outage_costs_one_attempt_per_minute_of_page_views(self, team, owner, report):
        from django.core.cache import cache

        from sbomify.apps.compliance.notifications import get_notifications

        cache.clear()
        CRAReport.objects.filter(pk=report.pk).update(reminders_pending=True)
        with patch.object(tasks, "schedule_reminders", side_effect=ConnectionError("down")) as schedule:
            get_notifications(_bell_request(team, owner))
            get_notifications(_bell_request(team, owner))

        assert schedule.call_count == 1


@pytest.mark.django_db
class TestFilingStageDefault:
    """Filings are append-only, so the stage the form submits by default must be the one that is due."""

    def _file_early_stages(self, report, owner):
        for stage in (Stage.EARLY_WARNING, Stage.NOTIFICATION):
            assert report_service.record_filing(report, owner, stage=stage).ok

    def _selected(self, page):
        import re

        select = re.search(r'<select[^>]*id="filingStage".*?</select>', page.content.decode(), re.S).group(0)
        return re.findall(r'<option value="([^"]*)"\s+selected', select)

    def test_after_the_notification_the_form_defaults_to_the_final_report(self, team, owner, report):
        self._file_early_stages(report, owner)

        page = _client_for(team, owner).get(reverse("compliance:cra_report_detail", args=[report.id]))

        assert page.context["filing_stage"] == Stage.FINAL_REPORT
        assert self._selected(page) == [Stage.FINAL_REPORT]

    def test_a_copy_tab_on_a_filed_stage_does_not_become_the_default(self, team, owner, report):
        self._file_early_stages(report, owner)

        url = reverse("compliance:cra_report_detail", args=[report.id]) + "?stage=early_warning"
        page = _client_for(team, owner).get(url)

        assert self._selected(page) == [Stage.FINAL_REPORT]


@pytest.mark.django_db
class TestBellFollowsTokenScope:
    def test_a_token_without_cra_report_manage_sees_no_cra_alerts(self, team, owner, report):
        from types import SimpleNamespace

        from sbomify.apps.compliance.notifications import get_notifications

        request = _bell_request(team, owner)
        with patch("sbomify.apps.compliance.notifications.timezone.now", return_value=AWARE + timedelta(hours=20)):
            assert len(get_notifications(request)) == 1
            request.access_token_record = SimpleNamespace(scopes=["workspace:read"])
            assert get_notifications(request) == []


@pytest.mark.django_db
def test_the_reminder_link_opens_the_report_in_its_own_workspace(team, report):
    """The detail view resolves a report in the session's workspace, so the link switches to it first."""
    tasks.send_due_reminders(now=AWARE + timedelta(hours=23))

    detail = reverse("compliance:cra_report_detail", args=[report.id])
    link = f"{reverse('workspaces:switch_team', args=[team.key])}?next={detail}"
    message = mail.outbox[0]
    assert link in message.body
    assert link in message.alternatives[0][0]


def _token_client(user: User, team: Workspace, scopes: list[str]) -> Client:
    encoded = create_personal_access_token(user)
    AccessToken.objects.create(user=user, encoded_token=encoded, description="reports", team=team, scopes=scopes)
    return Client(HTTP_AUTHORIZATION=f"Bearer {encoded}")


@pytest.mark.django_db
class TestManageOnlyToken:
    """A token scoped to manage reports can edit, file and delete them without also holding read."""

    def test_it_edits_and_files(self, team, owner, report):
        client = _token_client(owner, team, ["cra_report:manage"])

        patched = client.patch(
            f"/api/v1/compliance/cra-reports/{report.id}",
            data=json.dumps({"values": {"general_information": "Exploited in the wild."}}),
            content_type="application/json",
        )
        filed = client.post(
            f"/api/v1/compliance/cra-reports/{report.id}/filings",
            data=json.dumps(
                {"stage": "early_warning", "srp_reference": "SRP-9", "revision": patched.json()["revision"]}
            ),
            content_type="application/json",
        )

        assert patched.status_code == 200, patched.content
        assert filed.status_code == 201, filed.content

    def test_it_deletes(self, team, owner, report):
        client = _token_client(owner, team, ["cra_report:manage"])

        assert client.delete(f"/api/v1/compliance/cra-reports/{report.id}").status_code == 204
        assert not CRAReport.objects.filter(pk=report.pk).exists()

    def test_a_token_with_neither_still_sees_no_report(self, team, owner, report):
        client = _token_client(owner, team, ["workspace:read"])

        patched = client.patch(
            f"/api/v1/compliance/cra-reports/{report.id}",
            data=json.dumps({"values": {"general_information": "x"}}),
            content_type="application/json",
        )

        assert patched.status_code == 404
        assert client.delete(f"/api/v1/compliance/cra-reports/{report.id}").status_code == 404


@pytest.mark.django_db
class TestFilingWhatWasCopied:
    """A filing records the draft that was copied into ENISA, not one edited since."""

    def test_a_draft_edited_after_it_was_copied_is_not_filed(self, report, owner):
        copied = report.revision
        report_service.update_report(report, owner, values={"general_information": "Edited by someone else."})

        stale = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, revision=copied)

        assert stale.status_code == 409
        assert "changed" in stale.error
        assert not report.filings.exists()
        report.refresh_from_db()
        current = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, revision=report.revision)
        assert current.ok, current.error
        assert current.value.snapshot["srp_fields"]["general_information"] == "Edited by someone else."

    def test_the_page_files_only_the_revision_it_showed(self, team, owner, report):
        client = _client_for(team, owner)
        detail = client.get(reverse("compliance:cra_report_detail", args=[report.id])).content.decode()
        shown = report.revision
        assert f'name="revision" value="{shown}"' in detail
        report_service.update_report(report, owner, values={"general_information": "Edited by someone else."})

        response = client.post(
            reverse("compliance:cra_report_detail", args=[report.id]),
            {"action": "file", "stage": "early_warning", "srp_reference": "SRP-1", "revision": shown},
            follow=True,
        )

        assert not report.filings.exists()
        assert "This report changed" in response.content.decode()

    def test_the_api_refuses_a_stale_revision_and_requires_one(self, team, owner, report):
        client = _client_for(team, owner)
        copied = report.revision
        report_service.update_report(report, owner, values={"general_information": "Edited by someone else."})
        url = f"/api/v1/compliance/cra-reports/{report.id}/filings"

        stale = client.post(
            url,
            data=json.dumps({"stage": "early_warning", "revision": copied}),
            content_type="application/json",
        )
        missing = client.post(url, data=json.dumps({"stage": "early_warning"}), content_type="application/json")

        assert stale.status_code == 409
        assert missing.status_code in (400, 422)
        assert not report.filings.exists()


@pytest.mark.django_db
class TestFilingEvidence:
    """What a filing contained, and who recorded it, stays readable after the draft moves on."""

    def _filed_then_edited(self, report, owner):
        filing = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING, srp_reference="SRP-1").value
        report_service.update_report(report, owner, values={"general_information": "Written after the filing."})
        return filing

    def test_the_api_returns_the_snapshot_and_the_filer(self, team, owner, report):
        filing = self._filed_then_edited(report, owner)
        client = _client_for(team, _member(team, "member", "reader"))

        listed = client.get(f"/api/v1/compliance/cra-reports/{report.id}").json()["filings"]
        detail = client.get(f"/api/v1/compliance/cra-reports/{report.id}/filings/{filing.id}")

        assert listed[0]["filed_by"] == owner.email
        assert detail.status_code == 200, detail.content
        body = detail.json()
        assert body["filed_by"] == owner.email
        assert body["snapshot"]["srp_fields"]["title"] == "Router OS remote code execution"
        assert "general_information" not in body["snapshot"]["srp_fields"]

    def test_another_reports_filing_reads_as_absent(self, team, owner, product, report):
        filing = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING).value
        other = report_service.create_report(team, owner, kind="incident", product_id=product.id, aware_at=AWARE).value
        client = _client_for(team, owner)

        response = client.get(f"/api/v1/compliance/cra-reports/{other.id}/filings/{filing.id}")
        page = client.get(reverse("compliance:cra_report_filing", args=[other.id, filing.id]))

        assert response.status_code == 404
        assert page.status_code == 404

    def test_the_filings_table_links_each_filing_to_what_it_contained(self, team, owner, report):
        filing = self._filed_then_edited(report, owner)
        client = _client_for(team, _member(team, "member", "reader"))
        url = reverse("compliance:cra_report_filing", args=[report.id, filing.id])

        detail = client.get(reverse("compliance:cra_report_detail", args=[report.id])).content.decode()
        evidence = client.get(url)

        assert url in detail
        assert owner.email in detail
        assert evidence.status_code == 200
        html = evidence.content.decode()
        assert "Router OS remote code execution" in html
        assert "Written after the filing." not in html
        assert "SRP-1" in html

    def test_a_guest_cannot_read_a_filing(self, team, owner, report):
        filing = report_service.record_filing(report, owner, stage=Stage.EARLY_WARNING).value
        client = _client_for(team, _member(team, "guest", "visitor"))

        response = client.get(reverse("compliance:cra_report_filing", args=[report.id, filing.id]))

        assert response.status_code in (302, 403, 404)


@pytest.mark.django_db
class TestClosedReportDeadlines:
    def test_a_closed_report_shows_no_stage_overdue(self, team, owner, product):
        # Filed straight to the final report, long after the early warning was due.
        report = report_service.create_report(
            team, owner, kind="incident", product_id=product.id, aware_at=timezone.now() - timedelta(days=60)
        ).value
        report_service.record_filing(report, owner, stage=Stage.FINAL_REPORT, srp_reference="F")
        client = _client_for(team, owner)

        html = client.get(reverse("compliance:cra_report_detail", args=[report.id])).content.decode()

        assert "Overdue" not in html
