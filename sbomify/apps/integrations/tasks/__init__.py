"""Background syncs.

A sync is one request per control against someone else's API, so it never runs
in the request cycle, not even behind the "Sync now" button: that button
queues this and returns.
"""

from __future__ import annotations

from datetime import timedelta

import dramatiq
from django.db.models import Q
from django.utils import timezone

from sbomify.apps.integrations.models import Integration
from sbomify.apps.integrations.services.sync import run_sync
from sbomify.logging import getLogger
from sbomify.task_utils import record_task_breadcrumb

logger = getLogger(__name__)

# How stale a connection may get before the scheduler picks it up. Compliance
# state moves in days, so six hours is well inside what a trust center needs
# and well outside anything a provider would call chatty.
SYNC_INTERVAL = timedelta(hours=6)

# How long a claim on a connection stays good. This is the actor's own time
# limit: past it dramatiq has killed the run, so a claim still standing belongs
# to a worker that is no longer there and the next run may take it.
SYNC_LEASE = timedelta(minutes=30)


def _claim(integration_id: str) -> Integration | None:
    """Take this connection for this run, or decline it.

    Three things queue a sync, the button, the OAuth callback and the six-hour
    scheduler, so the same connection can be queued several times over while a
    run is still going. Two runs against one account duplicate every per-control
    request and let the slower one write its older answers last. The claim is a
    single conditional update, so the database picks the winner and the losers
    return without touching anything.

    It is also where a disconnect takes effect: the row is gone or no longer
    connected by the time the worker starts, nothing is claimed, and queued work
    stops rather than syncing an account nobody is connected to any more.
    """
    expired = timezone.now() - SYNC_LEASE
    claimed = (
        Integration.objects.filter(id=integration_id, status=Integration.Status.CONNECTED)
        .filter(~Q(last_sync_status=Integration.SyncStatus.RUNNING) | Q(updated_at__lt=expired))
        .update(last_sync_status=Integration.SyncStatus.RUNNING, updated_at=timezone.now())
    )
    if not claimed:
        return None
    return Integration.objects.filter(id=integration_id).select_related("team").first()


@dramatiq.actor(queue_name="integrations", max_retries=0, time_limit=1_800_000)
def sync_integration(integration_id: str) -> None:
    """Sync one connection. Retries are the scheduler's job, not dramatiq's.

    ``max_retries=0`` because a failure here is almost always the provider
    being unreachable or a credential being gone, and the next scheduled run
    is a better answer to both than three immediate attempts.
    """
    integration = _claim(integration_id)
    if integration is None:
        logger.info("Integration %s is gone, disconnected or already syncing, skipping", integration_id)
        return

    record_task_breadcrumb(
        "sync_integration",
        "start",
        data={"integration_id": integration_id, "provider": integration.provider},
    )
    result = run_sync(integration)
    if not result.ok:
        logger.warning(
            "Sync of %s for workspace %s failed: %s", integration.provider, integration.team.key, result.error
        )


@dramatiq.actor(queue_name="integrations", max_retries=0, time_limit=300_000)
def sync_due_integrations() -> None:
    """Queue a sync for every connection that has gone stale.

    Connections needing a reconnect are skipped: there is no credential to
    try, so queueing them would only refill the failure log every six hours.
    """
    cutoff = timezone.now() - SYNC_INTERVAL
    due = Integration.objects.filter(status=Integration.Status.CONNECTED).exclude(last_sync_at__gt=cutoff)

    queued = 0
    for integration_id in due.values_list("id", flat=True):
        sync_integration.send(integration_id)
        queued += 1

    record_task_breadcrumb("sync_due_integrations", "queued", data={"count": queued})
    logger.info("Queued %d integration syncs", queued)
