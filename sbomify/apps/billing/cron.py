"""
Cron job configuration for billing tasks.

This module defines the periodic tasks for billing-related operations.
These tasks are designed to work with dramatiq-crontab for scheduling.
"""

import dramatiq
from dramatiq_crontab import cron

from .tasks import check_stale_trials_task


# Schedule stale trial check to run daily at 2:00 AM UTC
# This acts as a safety net in case Stripe webhooks are missed
@cron("0 2 * * *")  # Daily at 2:00 AM UTC
@dramatiq.actor(
    queue_name="billing_cron",
    max_retries=1,
    time_limit=600000,  # 10 minute timeout
)
def daily_stale_trial_check():
    """
    Daily task to check for stale trial subscriptions.

    This task runs once per day as a safety net to catch trials that
    may have expired but weren't updated due to missed Stripe webhooks.

    The task:
    1. Finds teams with trials that appear to have expired (trial_end in past)
    2. Syncs their status with Stripe API
    3. Updates local database to match Stripe's actual state

    This is a defensive measure - normally trial expiration is handled by
    Stripe webhooks (customer.subscription.updated), but this catches any
    cases where webhooks were missed or failed to process.
    """
    return check_stale_trials_task.send()
