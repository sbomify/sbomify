"""Background syncs.

A sync is one request per control against someone else's API, so it never runs
in the request cycle, not even behind the "Sync now" button: that button
queues this and returns.
"""

from __future__ import annotations

from datetime import timedelta

import dramatiq
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


@dramatiq.actor(queue_name="integrations", max_retries=0, time_limit=1_800_000)
def sync_integration(integration_id: str) -> None:
    """Sync one connection. Retries are the scheduler's job, not dramatiq's.

    ``max_retries=0`` because a failure here is almost always the provider
    being unreachable or a credential being gone, and the next scheduled run
    is a better answer to both than three immediate attempts.
    """
    integration = Integration.objects.filter(id=integration_id).select_related("team").first()
    if integration is None:
        logger.info("Integration %s no longer exists, skipping sync", integration_id)
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
