"""
Cron job configuration for onboarding email tasks.

This module defines the periodic tasks for sending onboarding emails.
These tasks are designed to work with dramatiq-crontab for scheduling.
"""

import dramatiq
from dramatiq_crontab import cron

from .tasks import process_all_onboarding_reminders_task


# Schedule onboarding reminder processing to run daily at 9:00 AM UTC
# This will process first component/SBOM reminders that adapt based on user progress
@cron("0 9 * * *")  # Daily at 9:00 AM UTC
@dramatiq.actor(queue_name="onboarding_cron", max_retries=1, time_limit=600000)
def daily_onboarding_reminders():
    """
    Daily task to process all onboarding reminder emails.

    This task runs once per day and:
    1. Finds PRIMARY workspace owners eligible for the consolidated component/SBOM reminder
    2. Queues individual adaptive email tasks for each eligible user
    3. Ensures each user receives the email only once (tracks sent emails)

    The consolidated email adapts its content based on user progress and is sent only to workspace owners:
    - Component focus: 3+ days since signup, welcome email sent, no SBOM components created
    - SBOM focus: 7+ days since first component creation, has components but no SBOMs uploaded

    The task is scheduled to run at 9:00 AM UTC to ensure emails are sent
    during business hours in most timezones.
    """
    return process_all_onboarding_reminders_task.send()
