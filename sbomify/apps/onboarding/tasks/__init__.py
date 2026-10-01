"""
Dramatiq tasks for onboarding email processing.
"""

from __future__ import annotations

from typing import Any

import dramatiq
from django.contrib.auth import get_user_model
from dramatiq_crontab import cron

from sbomify.logging import getLogger
from sbomify.task_utils import record_task_breadcrumb

from ..models import OnboardingEmail
from ..services import OnboardingEmailService

User = get_user_model()
logger = getLogger(__name__)


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_welcome_email_task(user_id: int) -> None:
    """
    Send welcome email to a user.

    Args:
        user_id: ID of the user to send welcome email to
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        # User doesn't exist - log warning and exit without retry
        logger.warning("[TASK_send_welcome_email] User with ID %s not found, skipping", user_id)
        return

    logger.info("[TASK_send_welcome_email] Starting for user %s", user_id)
    record_task_breadcrumb("send_welcome_email_task", "start", data={"user_id": user_id})

    try:
        success = OnboardingEmailService.send_welcome_email(user)

        if success:
            logger.info("[TASK_send_welcome_email] Successfully sent welcome email to user %s", user_id)
            record_task_breadcrumb("send_welcome_email_task", "sent", data={"user_id": user_id})
        else:
            logger.warning("[TASK_send_welcome_email] Failed to send welcome email to user %s", user_id)
    except Exception as e:
        logger.error("[TASK_send_welcome_email] Error for user %s: %s", user_id, e)
        record_task_breadcrumb("send_welcome_email_task", "error", level="error", data={"error": str(e)})
        raise


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_drip_email_task(user_id: int, email_type: str) -> None:
    """Send one drip email to a user: quick start (day 1), first component (day 3),
    first SBOM (day 7) or collaboration (day 10)."""
    tag = f"[TASK_send_{email_type}]"
    breadcrumb = f"send_{email_type}_email_task"
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("%s User with ID %s not found, skipping", tag, user_id)
        return

    logger.info("%s Starting for user %s", tag, user_id)
    record_task_breadcrumb(breadcrumb, "start", data={"user_id": user_id})
    try:
        success = OnboardingEmailService.send_drip_email(user, email_type)
        if success:
            logger.info("%s Successfully sent to user %s", tag, user_id)
            record_task_breadcrumb(breadcrumb, "sent", data={"user_id": user_id})
        else:
            logger.warning("%s Failed to send to user %s", tag, user_id)
    except Exception as e:
        logger.error("%s Error for user %s: %s", tag, user_id, e)
        record_task_breadcrumb(breadcrumb, "error", level="error", data={"error": str(e)})
        raise


# Each drip email had its own actor before send_drip_email_task. The names stay
# registered so messages already queued under them still run.
@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_quick_start_email_task(user_id: int) -> None:
    send_drip_email_task(user_id, OnboardingEmail.EmailType.QUICK_START)


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_first_component_email_task(user_id: int) -> None:
    send_drip_email_task(user_id, OnboardingEmail.EmailType.FIRST_COMPONENT)


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_first_sbom_email_task(user_id: int) -> None:
    send_drip_email_task(user_id, OnboardingEmail.EmailType.FIRST_SBOM)


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_collaboration_email_task(user_id: int) -> None:
    send_drip_email_task(user_id, OnboardingEmail.EmailType.COLLABORATION)


@cron("0 9 * * *")  # type: ignore[untyped-decorator]  # Daily at 9:00 AM UTC
@dramatiq.actor(queue_name="onboarding_emails", max_retries=1, time_limit=300000)
def process_onboarding_sequence_batch_task() -> None:
    """
    Process all onboarding sequence emails for eligible users.

    Finds users eligible for each email type and queues individual tasks. The
    welcome email is not part of this: a signal queues it when the user is created.
    """
    try:
        logger.info("[TASK_process_onboarding_sequence] Starting batch processing")
        eligible_by_type = OnboardingEmailService.get_users_for_onboarding_sequence()

        total_queued = 0
        failed_to_queue = 0
        for email_type, users in eligible_by_type.items():
            for user in users:
                try:
                    send_drip_email_task.send(user.id, email_type)
                    total_queued += 1
                except Exception as e:
                    failed_to_queue += 1
                    logger.error(
                        "[TASK_process_onboarding_sequence] Failed to queue %s for user %s: %s",
                        email_type,
                        user.id,
                        e,
                    )

        logger.info("[TASK_process_onboarding_sequence] Completed: %d queued, %d failed", total_queued, failed_to_queue)
    except Exception as e:
        logger.error("[TASK_process_onboarding_sequence] Batch processing error: %s", e)
        raise


# Convenience functions for triggering tasks from signals or other parts of the application


def queue_welcome_email(user: Any) -> str:
    """
    Queue a welcome email task for a user.

    Args:
        user: User instance

    Returns:
        Task message ID
    """
    logger.info("Queueing welcome email for user %s", user.id)
    # Delay 10s to ensure team/trial setup completes before email context is built
    result = send_welcome_email_task.send_with_options(args=(user.id,), delay=10000)
    return result.message_id
