"""Background checks of TEA subscriptions.

An hourly cron queues every subscription that is due. Each check that runs
also queues its own next run as a delayed message, so subscriptions keep being
checked on a deployment that runs no scheduler. The lease in ``sync.check``
makes a duplicate message harmless: it finds the subscription not due, or held.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import dramatiq
from django.db.models import Q
from django.utils import timezone
from dramatiq_crontab import cron

from sbomify.apps.tea.models import TeaSubscription
from sbomify.apps.tea.sync import check
from sbomify.apps.teams.broadcasts import broadcast_on_commit

logger = logging.getLogger(__name__)

CHECK_TIME_LIMIT_MS = 15 * 60 * 1000


@cron("41 * * * *")  # type: ignore[untyped-decorator]  # Hourly, off :00 like the other jobs
@dramatiq.actor(queue_name="tea_monitoring", max_retries=0, time_limit=300_000)
def queue_due_tea_checks() -> None:
    now = timezone.now()
    free = Q(lease_until__isnull=True) | Q(lease_until__lt=now)
    due = TeaSubscription.objects.filter(free, next_check_at__lte=now).values_list("pk", flat=True)
    for subscription_id in due:
        check_tea_subscription.send(subscription_id)


@dramatiq.actor(queue_name="tea_monitoring", max_retries=0, time_limit=CHECK_TIME_LIMIT_MS)
def check_tea_subscription(subscription_id: str, force: bool = False) -> None:
    subscription = check(subscription_id, force=force)
    if subscription is None:
        return
    delay = max(subscription.next_check_at - timezone.now(), timedelta(minutes=1))
    check_tea_subscription.send_with_options(args=(subscription_id,), delay=int(delay.total_seconds() * 1000))
    broadcast_on_commit(
        subscription.component.team.key,
        "tea_subscription_checked",
        {"component_id": subscription.component_id, "status": subscription.status},
    )
