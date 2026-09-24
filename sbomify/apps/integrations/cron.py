"""Scheduled integration syncs.

Runs at :17 to keep it off the top of the hour, where every other scheduled
job in this deployment already is.
"""

import dramatiq
from dramatiq_crontab import cron

from .tasks import sync_due_integrations


@cron("17 */6 * * *")  # type: ignore[untyped-decorator]
@dramatiq.actor(
    queue_name="integrations_cron",
    max_retries=0,
    time_limit=300000,
)
def periodic_integration_sync() -> None:
    """Queue a sync for every connection that has not run in six hours."""
    sync_due_integrations.send()
