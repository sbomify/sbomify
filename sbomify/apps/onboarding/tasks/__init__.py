"""
Dramatiq tasks for onboarding email processing.
"""

import dramatiq
from django.contrib.auth import get_user_model

from sbomify.logging import getLogger
from sbomify.task_utils import record_task_breadcrumb

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
def send_first_component_sbom_email_task(user_id: int) -> None:
    """
    Send first component & SBOM reminder email to a user.

    This email adapts based on user progress:
    - Component focus if no components created
    - SBOM focus if components exist but no SBOMs

    Args:
        user_id: ID of the user to send reminder email to
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        # User doesn't exist - log warning and exit without retry
        logger.warning("[TASK_send_first_component_sbom] User with ID %s not found, skipping", user_id)
        return

    logger.info("[TASK_send_first_component_sbom] Starting for user %s", user_id)
    record_task_breadcrumb("send_first_component_sbom_email_task", "start", data={"user_id": user_id})

    try:
        success = OnboardingEmailService.send_first_component_sbom_email(user)

        if success:
            logger.info("[TASK_send_first_component_sbom] Successfully sent reminder to user %s", user_id)
            record_task_breadcrumb("send_first_component_sbom_email_task", "sent", data={"user_id": user_id})
        else:
            logger.warning("[TASK_send_first_component_sbom] Failed to send reminder to user %s", user_id)
    except Exception as e:
        logger.error("[TASK_send_first_component_sbom] Error for user %s: %s", user_id, e)
        record_task_breadcrumb("send_first_component_sbom_email_task", "error", level="error", data={"error": str(e)})
        raise


@dramatiq.actor(queue_name="onboarding_emails", max_retries=1, time_limit=300000)
def process_first_component_sbom_reminders_batch_task() -> None:
    """
    Process first component & SBOM reminders for all eligible users.

    This task finds all users who should receive either component creation
    or SBOM upload reminders and queues individual email tasks for them.
    """
    try:
        logger.info("[TASK_process_first_component_sbom_reminders] Starting batch processing")

        eligible_users = OnboardingEmailService.get_users_for_first_component_sbom_reminder()
        user_count = eligible_users.count()

        logger.info("[TASK_process_first_component_sbom_reminders] Found %d eligible users", user_count)

        queued_tasks = 0
        for user in eligible_users:
            try:
                # Queue individual email task
                send_first_component_sbom_email_task.send(user.id)
                queued_tasks += 1
                logger.debug("[TASK_process_first_component_sbom_reminders] Queued task for user %s", user.id)
            except Exception as e:
                logger.error(
                    "[TASK_process_first_component_sbom_reminders] Failed to queue task for user %s: %s",
                    user.id,
                    e,
                )

        logger.info(
            "[TASK_process_first_component_sbom_reminders] Completed: %d/%d tasks queued",
            queued_tasks,
            user_count,
        )

    except Exception as e:
        logger.error("[TASK_process_first_component_sbom_reminders] Batch processing error: %s", e)
        raise


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_quick_start_email_task(user_id: int) -> None:
    """Send quick start guide email to a user (day 1)."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("[TASK_send_quick_start] User with ID %s not found, skipping", user_id)
        return

    logger.info("[TASK_send_quick_start] Starting for user %s", user_id)
    record_task_breadcrumb("send_quick_start_email_task", "start", data={"user_id": user_id})
    try:
        success = OnboardingEmailService.send_quick_start_email(user)
        if success:
            logger.info("[TASK_send_quick_start] Successfully sent to user %s", user_id)
            record_task_breadcrumb("send_quick_start_email_task", "sent", data={"user_id": user_id})
        else:
            logger.warning("[TASK_send_quick_start] Failed to send to user %s", user_id)
    except Exception as e:
        logger.error("[TASK_send_quick_start] Error for user %s: %s", user_id, e)
        record_task_breadcrumb("send_quick_start_email_task", "error", level="error", data={"error": str(e)})
        raise


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_first_component_email_task(user_id: int) -> None:
    """Send first component reminder email to a user (day 3)."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("[TASK_send_first_component] User with ID %s not found, skipping", user_id)
        return

    logger.info("[TASK_send_first_component] Starting for user %s", user_id)
    record_task_breadcrumb("send_first_component_email_task", "start", data={"user_id": user_id})
    try:
        success = OnboardingEmailService.send_first_component_email(user)
        if success:
            logger.info("[TASK_send_first_component] Successfully sent to user %s", user_id)
            record_task_breadcrumb("send_first_component_email_task", "sent", data={"user_id": user_id})
        else:
            logger.warning("[TASK_send_first_component] Failed to send to user %s", user_id)
    except Exception as e:
        logger.error("[TASK_send_first_component] Error for user %s: %s", user_id, e)
        record_task_breadcrumb("send_first_component_email_task", "error", level="error", data={"error": str(e)})
        raise


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_first_sbom_email_task(user_id: int) -> None:
    """Send first SBOM upload reminder email to a user (day 7)."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("[TASK_send_first_sbom] User with ID %s not found, skipping", user_id)
        return

    logger.info("[TASK_send_first_sbom] Starting for user %s", user_id)
    record_task_breadcrumb("send_first_sbom_email_task", "start", data={"user_id": user_id})
    try:
        success = OnboardingEmailService.send_first_sbom_email(user)
        if success:
            logger.info("[TASK_send_first_sbom] Successfully sent to user %s", user_id)
            record_task_breadcrumb("send_first_sbom_email_task", "sent", data={"user_id": user_id})
        else:
            logger.warning("[TASK_send_first_sbom] Failed to send to user %s", user_id)
    except Exception as e:
        logger.error("[TASK_send_first_sbom] Error for user %s: %s", user_id, e)
        record_task_breadcrumb("send_first_sbom_email_task", "error", level="error", data={"error": str(e)})
        raise


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
def send_collaboration_email_task(user_id: int) -> None:
    """Send collaboration/invite email to a user (day 10)."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("[TASK_send_collaboration] User with ID %s not found, skipping", user_id)
        return

    logger.info("[TASK_send_collaboration] Starting for user %s", user_id)
    record_task_breadcrumb("send_collaboration_email_task", "start", data={"user_id": user_id})
    try:
        success = OnboardingEmailService.send_collaboration_email(user)
        if success:
            logger.info("[TASK_send_collaboration] Successfully sent to user %s", user_id)
            record_task_breadcrumb("send_collaboration_email_task", "sent", data={"user_id": user_id})
        else:
            logger.warning("[TASK_send_collaboration] Failed to send to user %s", user_id)
    except Exception as e:
        logger.error("[TASK_send_collaboration] Error for user %s: %s", user_id, e)
        record_task_breadcrumb("send_collaboration_email_task", "error", level="error", data={"error": str(e)})
        raise


@dramatiq.actor(queue_name="onboarding_emails", max_retries=1, time_limit=300000)
def process_onboarding_sequence_batch_task() -> None:
    """
    Process all onboarding sequence emails for eligible users.

    Finds users eligible for each email type and queues individual tasks.
    """
    from ..models import OnboardingEmail as OE

    task_map = {
        OE.EmailType.QUICK_START: send_quick_start_email_task,
        OE.EmailType.FIRST_COMPONENT: send_first_component_email_task,
        OE.EmailType.FIRST_SBOM: send_first_sbom_email_task,
        OE.EmailType.COLLABORATION: send_collaboration_email_task,
    }

    try:
        logger.info("[TASK_process_onboarding_sequence] Starting batch processing")
        eligible_by_type = OnboardingEmailService.get_users_for_onboarding_sequence()

        total_queued = 0
        failed_to_queue = 0
        for email_type, users in eligible_by_type.items():
            task_fn = task_map.get(email_type)
            if not task_fn:
                logger.warning("[TASK_process_onboarding_sequence] No task function for email type %s", email_type)
                continue
            for user in users:
                try:
                    task_fn.send(user.id)
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


@dramatiq.actor(queue_name="onboarding_emails", max_retries=1, time_limit=600000)
def process_all_onboarding_reminders_task() -> None:
    """
    Process all onboarding reminder emails.

    This is a master task that processes both the legacy first component/SBOM reminders
    and the new onboarding sequence emails.
    It's designed to be run on a schedule (e.g., daily via cron or periodic task).
    """
    try:
        logger.info("[TASK_process_all_onboarding_reminders] Starting comprehensive onboarding email processing")

        # Process legacy first component/SBOM reminders
        process_first_component_sbom_reminders_batch_task.send_with_options(args=(), delay=0)

        # Process new onboarding sequence emails
        process_onboarding_sequence_batch_task.send_with_options(args=(), delay=0)

        logger.info("[TASK_process_all_onboarding_reminders] Successfully queued all reminder processing tasks")

    except Exception as e:
        logger.error("[TASK_process_all_onboarding_reminders] Error: %s", e)
        raise


# Convenience functions for triggering tasks from signals or other parts of the application


def queue_welcome_email(user) -> str:
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


def queue_first_component_sbom_reminder(user) -> str:
    """
    Queue a first component/SBOM reminder email task for a user.

    Args:
        user: User instance

    Returns:
        Task message ID
    """
    logger.info("Queueing first component/SBOM reminder for user %s", user.id)
    result = send_first_component_sbom_email_task.send(user.id)
    return result.message_id
