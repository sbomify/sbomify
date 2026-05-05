"""
Cron job configuration for onboarding email tasks.

This module defines the periodic tasks for sending onboarding emails.
These tasks are designed to work with dramatiq-crontab for scheduling.
"""

from __future__ import annotations

import dramatiq
from dramatiq_crontab import cron

from .tasks import process_all_onboarding_reminders_task


# Schedule onboarding reminder processing to run weekly on Monday at 9:00 AM UTC.
# Note: dramatiq-crontab requires a literal day name (Mon/Tue/...) — numeric forms raise ValueError.
@cron("0 9 * * Mon")  # type: ignore[untyped-decorator]  # Weekly on Monday at 9:00 AM UTC
@dramatiq.actor(queue_name="onboarding_cron", max_retries=1, time_limit=600000)
def weekly_onboarding_reminders() -> None:
    """
    Weekly task to process all onboarding reminder emails.

    Runs every Monday at 9:00 AM UTC and:
    1. Finds PRIMARY workspace owners eligible for the consolidated component/SBOM reminder
    2. Queues individual adaptive email tasks for each eligible user
    3. Ensures each user receives the email only once (tracks sent emails)

    The consolidated email adapts its content based on user progress and is sent only to workspace owners:
    - Component focus: 3+ days since signup, welcome email sent, no SBOM components created
    - SBOM focus: 7+ days since first component creation, has components but no SBOMs uploaded
    """
    process_all_onboarding_reminders_task.send()
