"""
Cron job configuration for onboarding email tasks.

This module defines the periodic tasks for sending onboarding emails.
These tasks are designed to work with dramatiq-crontab for scheduling.
"""

from __future__ import annotations

import dramatiq
from dramatiq_crontab import cron

from .tasks import process_all_onboarding_reminders_task


# Schedule onboarding reminder processing to run daily at 9:00 AM UTC.
# Drives the 4-stage drip: quick start → first component → first SBOM → collaboration.
@cron("0 9 * * *")  # type: ignore[untyped-decorator]  # Daily at 9:00 AM UTC
@dramatiq.actor(queue_name="onboarding_cron", max_retries=1, time_limit=600000)
def daily_onboarding_reminders() -> None:
    """
    Daily task to process onboarding reminder emails.

    Runs once per day at 09:00 UTC and fans out the drip sequence:

      - Quick Start (day 1)
      - First Component (day 3, no component yet)
      - First SBOM (day 7, component created but no SBOM yet)
      - Collaboration (day 10, solo workspace)

    Per-user/per-type dedup is enforced by the ``OnboardingEmail`` table's
    unique ``(user, email_type)`` constraint plus an explicit sent-emails
    pre-filter in ``OnboardingEmailService.get_users_for_onboarding_sequence``.
    """
    process_all_onboarding_reminders_task.send()
