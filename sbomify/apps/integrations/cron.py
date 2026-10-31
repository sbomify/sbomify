"""Scheduled integration work: syncs, and the daily vulnerability digest.

Both run off the top of the hour, where every other scheduled job in this
deployment already is.
"""

import dramatiq
from dramatiq_crontab import cron

from .tasks import sync_due_integrations
from .tasks.notifications import send_due_digests


@cron("17 */6 * * *")  # type: ignore[untyped-decorator]
@dramatiq.actor(
    queue_name="integrations_cron",
    max_retries=0,
    time_limit=300000,
)
def periodic_integration_sync() -> None:
    """Queue a sync for every connection that has not run in six hours."""
    sync_due_integrations.send()


# 08:00 UTC is the digest time the settings tab promises, so it must not drift
# off the hour the way the sync does.
@cron("0 8 * * *")  # type: ignore[untyped-decorator]
@dramatiq.actor(
    queue_name="integrations_cron",
    max_retries=0,
    time_limit=300000,
)
def periodic_vulnerability_digest() -> None:
    """Queue the daily digest for every workspace that routes one to a channel."""
    send_due_digests.send()
