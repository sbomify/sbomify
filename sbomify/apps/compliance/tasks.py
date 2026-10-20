"""Email reminders before each CRA Article 14 deadline.

When a report is created, edited or filed, two delayed messages are queued
for every deadline still open: one six hours before it, one at it, so a missed
early warning does not silence the notification due after it. Production runs
no scheduler, so these delayed messages are what reminds people there; the
hourly cron sweep is a backstop wherever a scheduler does run. Each reminder to
each person is claimed before it is sent (:class:`~.models.CRAReportReminder`),
so a message delivered twice, or a sweep that overlaps one, mails nobody twice,
and a failed send is retried for that person alone. A claim still held by a
worker that may have died queues the report's message again for when it
expires. A message checks the report when it runs, so one queued before a
filing sends nothing after it. A write that cannot reach the broker leaves its
report marked ``reminders_pending``, and :func:`dispatch_pending_reminders`
queues it later, from an owner or admin page view or from the sweep.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import dramatiq
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from dramatiq_crontab import cron

from sbomify.apps.compliance.reporting import STAGE_LABELS, open_deadlines
from sbomify.apps.core.url_utils import get_base_url
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.compliance.models import CRAReport

logger = getLogger(__name__)

REMINDER_LEAD = timedelta(hours=6)
# Longer than either actor's time limit, so a live worker's claim is never taken over.
CLAIM_TIMEOUT = timedelta(minutes=10)


def _recipients(team_id: int) -> list[str]:
    """Owners and admins: filing is theirs to do."""
    from sbomify.apps.core.authz import ADMINISTER
    from sbomify.apps.teams.models import Member

    emails = Member.objects.filter(team_id=team_id, role__in=ADMINISTER).values_list("user__email", flat=True)
    return sorted({email for email in emails if email})


class ReminderDeliveryFailed(Exception):
    """Some reminders could not be sent. Raised after the rest went out, so the retry sends only those."""


def _claim(
    report: "CRAReport", stage: str, due: datetime, threshold: str, recipient: str, now: datetime
) -> int | datetime | None:
    """Claim one reminder for one person.

    Returns the row's id when this worker may send it, None when it was already
    sent, or the time another worker's claim expires when one still holds it.
    """
    from sbomify.apps.compliance.models import CRAReportReminder

    identity = {"report": report, "stage": stage, "due": due, "threshold": threshold, "recipient": recipient}
    try:
        with transaction.atomic():
            row = CRAReportReminder.objects.create(**identity, claimed_at=now)
        return row.pk
    except IntegrityError:
        pass
    # The row exists. Take it over only if it is unsent and its claim was
    # released after a failed send or left by a worker that died. The
    # conditional update is the atomic step: two workers cannot both win it.
    takeable = CRAReportReminder.objects.filter(**identity, sent_at__isnull=True).filter(
        Q(claimed_at__isnull=True) | Q(claimed_at__lt=now - CLAIM_TIMEOUT)
    )
    pk = takeable.values_list("pk", flat=True).first()
    if pk is not None and takeable.filter(pk=pk).update(claimed_at=now):
        return pk
    held = CRAReportReminder.objects.filter(**identity).values_list("sent_at", "claimed_at").first()
    if held is None or held[0] is not None or held[1] is None:
        return None
    return held[1] + CLAIM_TIMEOUT


def send_due_reminders(*, report_id: str | None = None, now: datetime | None = None) -> int:
    """Send the reminders that are due, for every open deadline. Returns how many emails went out.

    Raises :class:`ReminderDeliveryFailed` after the loop when any send failed,
    so the actor's retries apply. What did go out is already marked sent.
    """
    from sbomify.apps.compliance.models import CRAReport, CRAReportReminder

    now = now or timezone.now()
    reports = (
        CRAReport.objects.exclude(filings__stage="final_report")
        .select_related("product", "team")
        .prefetch_related("filings")
    )
    if report_id:
        reports = reports.filter(pk=report_id)

    sent = 0
    failed: list[str] = []
    # A claim another worker still holds may belong to one that died. Nothing
    # else would come back for it without the sweep, so the report's own
    # message is queued again for when the claim expires.
    retry_at: dict[str, datetime] = {}
    for report in reports:
        deadlines = open_deadlines(
            report.kind, report.aware_at, report.measure_available_at, filed=report.filed_stages()
        )
        for stage, due in deadlines:
            if due is None:
                continue
            crossed = [name for name, at in (("soon", due - REMINDER_LEAD), ("due", due)) if now >= at]
            if not crossed:
                continue
            recipients = _recipients(report.team_id)
            if not recipients:
                # Nothing claimed, so an address added later still gets the reminder.
                logger.warning(f"CRA report {report.pk} has a deadline but no owner or admin to remind")
                continue

            label = STAGE_LABELS[stage]
            overdue = now > due
            context = {
                "report": report,
                "stage_label": label,
                "due": due,
                "overdue": overdue,
                "base_url": get_base_url(),
            }
            state = "is overdue" if overdue else f"is due {due:%d %b %Y %H:%M} UTC"
            subject = f"CRA {label.lower()} for {report.product.name} {state}"
            body = render_to_string("compliance/emails/cra_report_reminder.txt", context)
            html = render_to_string("compliance/emails/cra_report_reminder.html.j2", context)

            for recipient in recipients:
                claimed = []
                for name in crossed:
                    outcome = _claim(report, stage, due, name, recipient, now)
                    if isinstance(outcome, int):
                        claimed.append(outcome)
                    elif isinstance(outcome, datetime):
                        retry_at[report.pk] = min(outcome, retry_at.get(report.pk, outcome))
                if not claimed:
                    continue
                email = EmailMultiAlternatives(
                    subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[recipient]
                )
                email.attach_alternative(html, "text/html")
                try:
                    email.send()
                except Exception:
                    logger.exception(f"Could not send a CRA reminder for report {report.pk}")
                    # Released, so the retry can claim it again at once.
                    CRAReportReminder.objects.filter(pk__in=claimed).update(claimed_at=None)
                    failed.append(f"{report.pk}/{stage}")
                    continue
                CRAReportReminder.objects.filter(pk__in=claimed).update(sent_at=now)
                sent += 1
    for pk, at in retry_at.items():
        delay = max(0, int((at - now).total_seconds() * 1000)) + 1000
        send_cra_report_reminders.send_with_options(args=(pk,), delay=delay)
    if failed:
        raise ReminderDeliveryFailed(f"{len(failed)} CRA reminder email(s) could not be sent: {', '.join(failed)}")
    return sent


@dramatiq.actor(queue_name="cra_reports", max_retries=3, time_limit=120000)
def send_cra_report_reminders(report_id: str) -> None:
    send_due_reminders(report_id=report_id)


def schedule_reminders(report: "CRAReport", *, now: datetime | None = None) -> None:
    """Queue a reminder six hours before every open deadline and one at it."""
    now = now or timezone.now()
    deadlines = open_deadlines(report.kind, report.aware_at, report.measure_available_at, filed=report.filed_stages())
    for _stage, due in deadlines:
        if due is None:
            continue
        for at in (due - REMINDER_LEAD, due):
            delay = max(0, int((at - now).total_seconds() * 1000))
            send_cra_report_reminders.send_with_options(args=(report.pk,), delay=delay)


def dispatch_pending_reminders(*, workspace_key: str | None = None) -> int:
    """Queue the reminders of reports whose scheduling never reached the broker.

    A write marks its report ``reminders_pending`` before it tries to queue
    anything and clears the mark once it has, so a broker outage leaves the mark
    set. Returns how many reports were scheduled; one that fails again stays
    marked for the next call.
    """
    from sbomify.apps.compliance.models import CRAReport

    pending = CRAReport.objects.filter(reminders_pending=True)
    if workspace_key:
        pending = pending.filter(team__key=workspace_key)
    return sum(schedule_pending(pk) for pk in pending.values_list("pk", flat=True))


def schedule_pending(report_id: str) -> bool:
    """Queue a marked report's reminders, from the report as it stands once claimed.

    The mark is cleared before scheduling, not after, so a write that marks the
    report again meanwhile keeps its mark even if its own queueing fails. A
    failure here puts the mark back. Returns whether this call scheduled it.
    """
    from sbomify.apps.compliance.models import CRAReport

    if not CRAReport.objects.filter(pk=report_id, reminders_pending=True).update(reminders_pending=False):
        return False
    report = CRAReport.objects.prefetch_related("filings").filter(pk=report_id).first()
    if report is None:
        return False
    try:
        schedule_reminders(report)
    except Exception:
        CRAReport.objects.filter(pk=report_id).update(reminders_pending=True)
        logger.exception(f"Could not queue CRA reminders for report {report_id}; they stay pending")
        return False
    return True


@cron("15 * * * *")  # type: ignore[untyped-decorator]  # Hourly, wherever a scheduler runs
@dramatiq.actor(queue_name="cra_reports", max_retries=1, time_limit=300000)
def sweep_cra_report_reminders() -> None:
    dispatch_pending_reminders()
    logger.info("Sent %s CRA report reminders", send_due_reminders())
