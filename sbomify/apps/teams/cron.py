"""
Cron job configuration for team/workspace domain verification tasks.

This module defines the periodic tasks for verifying custom domains.
These tasks are designed to work with dramatiq-crontab for scheduling.
"""

import dramatiq
from dramatiq_crontab import cron

from .tasks import verify_custom_domains


# Schedule domain verification to run every 15 minutes
# This checks unvalidated domains with exponential backoff
@cron("*/15 * * * *")  # Every 15 minutes
@dramatiq.actor(queue_name="domain_verification_cron", max_retries=1, time_limit=300000)
def periodic_domain_verification():
    """
    Periodic task to verify custom domains.

    This task runs every 15 minutes and:
    1. Finds teams with unvalidated custom domains
    2. Checks if enough time has passed based on exponential backoff
    3. Sends probe requests to verify DNS configuration
    4. Auto-validates domains when traffic is received (via middleware)

    The task uses exponential backoff to avoid spamming domains:
    - First attempt: immediate
    - After 1st failure: wait 5 minutes
    - After 2nd failure: wait 10 minutes
    - After 3rd failure: wait 20 minutes
    - And so on...

    The task is scheduled to run every 15 minutes to balance timely
    verification with resource usage.
    """
    return verify_custom_domains.send()
