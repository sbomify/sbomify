"""Bell notifications for CRA Article 14 deadlines.

Pull-based like every provider in NOTIFICATION_PROVIDERS, so it needs no
scheduler: computed per request from each open report's next deadline. Shown
to owners and admins, who are the ones who file.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.notifications.schemas import NotificationSchema

# Early warnings are due a day after the report starts, so a day's notice
# covers every stage without flagging a final report weeks ahead.
WARNING_WINDOW = timedelta(hours=24)
DISPATCH_COOLDOWN_SECONDS = 60


def get_notifications(request: HttpRequest) -> list[NotificationSchema]:
    if not request.user.is_authenticated:
        return []

    from sbomify.apps.compliance.models import CRAReport
    from sbomify.apps.core.authz import can
    from sbomify.apps.teams.models import Workspace

    workspace_key = (request.session.get("current_workspace") or {}).get("key")
    workspace = Workspace.objects.filter(key=workspace_key).first() if workspace_key else None
    # Through can(), like the other providers, so a token's scope narrows it too.
    if workspace is None or not can(request, "cra_report:manage", workspace):
        return []

    from sbomify.apps.compliance.tasks import dispatch_pending_reminders

    # Production runs no scheduler, so an owner or admin page view is what
    # schedules reminders a broker outage left unqueued. At most one view a
    # minute per workspace tries, so an outage costs one attempt, not one per
    # page view; an unreachable cache skips the attempt, as the broker is down too.
    if cache.add(f"cra-reminder-dispatch:{workspace_key}", True, DISPATCH_COOLDOWN_SECONDS):
        dispatch_pending_reminders(workspace_key=workspace_key)

    now = timezone.now()
    reports = (
        CRAReport.objects.filter(team__key=workspace_key)
        .exclude(filings__stage="final_report")
        .select_related("product")
        .prefetch_related("filings")
    )
    notifications = []
    for report in reports:
        nxt = report.next_due(now)
        if nxt is None or nxt.due is None or nxt.due - now > WARNING_WINDOW:
            continue
        state = "overdue" if nxt.overdue else "soon"
        if nxt.overdue:
            when = "is overdue"
        else:
            hours = max(1, int((nxt.due - now).total_seconds() // 3600))
            when = f"is due in {hours} hour{'' if hours == 1 else 's'}"
        notifications.append(
            NotificationSchema(
                # Changes when the report goes overdue, so a dismissed "due soon"
                # comes back as "overdue", and when the deadline is corrected, so
                # a dismissed alert does not hide the new date.
                id=f"cra_report_{report.pk}_{nxt.stage}_{int(nxt.due.timestamp())}_{state}",
                type="cra_report_deadline",
                message=f"{nxt.label} for {report.product.name} {when}.",
                action_url=reverse("compliance:cra_report_detail", args=[report.pk]),
                severity="error" if nxt.overdue else "warning",
                created_at=now.isoformat(),
            )
        )
    return notifications
