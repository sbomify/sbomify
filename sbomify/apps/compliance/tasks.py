"""Email reminders before each CRA Article 14 deadline.

When a report is created, edited or filed, two delayed messages are queued
for its next deadline: one six hours before it, one at it. Production runs no
scheduler, so these delayed messages are what reminds people there; the hourly
cron sweep is a backstop wherever a scheduler does run. Each reminder is sent
once (:class:`~.models.CRAReportReminder`), so a message delivered twice, or a
sweep that overlaps one, mails nobody twice. A message checks the report when
it runs, so one queued before a filing sends nothing after it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import dramatiq
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from dramatiq_crontab import cron

from sbomify.apps.core.url_utils import get_base_url
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.compliance.models import CRAReport

logger = getLogger(__name__)

REMINDER_LEAD = timedelta(hours=6)


def _recipients(team_id: int) -> list[str]:
    """Owners and admins: filing is theirs to do."""
    from sbomify.apps.core.authz import ADMINISTER
    from sbomify.apps.teams.models import Member

    emails = Member.objects.filter(team_id=team_id, role__in=ADMINISTER).values_list("user__email", flat=True)
    return sorted({email for email in emails if email})


def send_due_reminders(*, report_id: str | None = None, now: datetime | None = None) -> int:
    """Send the reminders that are due. Returns how many emails went out."""
    from sbomify.apps.compliance.models import CRAReport, CRAReportReminder

    now = now or timezone.now()
    reports = (
        CRAReport.objects.exclude(filings__stage="final_report")
        .select_related("product", "team")
        .prefetch_related("filings", "reminders")
    )
    if report_id:
        reports = reports.filter(pk=report_id)

    sent = 0
    for report in reports:
        nxt = report.next_due(now)
        if nxt is None or nxt.due is None:
            continue
        crossed = [name for name, at in (("soon", nxt.due - REMINDER_LEAD), ("due", nxt.due)) if now >= at]
        already = {r.threshold for r in report.reminders.all() if r.stage == nxt.stage}
        unsent = [name for name in crossed if name not in already]
        if not unsent:
            continue

        recipients = _recipients(report.team_id)
        if not recipients:
            # Unmarked, so an address added later still gets the reminder.
            logger.warning(f"CRA report {report.pk} has a deadline but no owner or admin to remind")
            continue

        context = {
            "report": report,
            "stage_label": nxt.label,
            "due": nxt.due,
            "overdue": nxt.overdue,
            "base_url": get_base_url(),
        }
        state = "is overdue" if nxt.overdue else f"is due {nxt.due:%d %b %Y %H:%M} UTC"
        subject = f"CRA {nxt.label.lower()} for {report.product.name} {state}"
        body = render_to_string("compliance/emails/cra_report_reminder.txt", context)
        html = render_to_string("compliance/emails/cra_report_reminder.html.j2", context)

        delivered = 0
        for recipient in recipients:
            email = EmailMultiAlternatives(
                subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[recipient]
            )
            email.attach_alternative(html, "text/html")
            try:
                email.send()
                delivered += 1
            except Exception:
                logger.exception(f"Could not send a CRA reminder for report {report.pk}")
        sent += delivered
        if delivered < len(recipients):
            continue  # left unmarked so the next message or sweep retries
        CRAReportReminder.objects.bulk_create(
            [CRAReportReminder(report=report, stage=nxt.stage, threshold=name) for name in unsent],
            ignore_conflicts=True,
        )
    return sent


@dramatiq.actor(queue_name="cra_reports", max_retries=3, time_limit=120000)
def send_cra_report_reminders(report_id: str) -> None:
    send_due_reminders(report_id=report_id)


def schedule_reminders(report: "CRAReport", *, now: datetime | None = None) -> None:
    """Queue a reminder six hours before the next deadline and one at it."""
    now = now or timezone.now()
    nxt = report.next_due(now)
    if nxt is None or nxt.due is None:
        return
    for at in (nxt.due - REMINDER_LEAD, nxt.due):
        delay = max(0, int((at - now).total_seconds() * 1000))
        send_cra_report_reminders.send_with_options(args=(report.pk,), delay=delay)


@cron("15 * * * *")  # type: ignore[untyped-decorator]  # Hourly, wherever a scheduler runs
@dramatiq.actor(queue_name="cra_reports", max_retries=1, time_limit=300000)
def sweep_cra_report_reminders() -> None:
    logger.info("Sent %s CRA report reminders", send_due_reminders())
