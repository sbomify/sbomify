"""
Dramatiq tasks for onboarding email processing.
"""

import dramatiq
from django.contrib.auth import get_user_model
from django.utils import timezone
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from sbomify.logging import getLogger

from .services import OnboardingEmailService

User = get_user_model()
logger = getLogger(__name__)


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
)
def send_welcome_email_task(user_id: int) -> dict:
    """
    Send welcome email to a user.

    Args:
        user_id: ID of the user to send welcome email to

    Returns:
        Dictionary with task results
    """
    try:
        user = User.objects.get(id=user_id)
        logger.info(f"[TASK_send_welcome_email] Starting for user {user.email}")

        success = OnboardingEmailService.send_welcome_email(user)

        result = {
            "user_id": user_id,
            "user_email": user.email,
            "success": success,
            "timestamp": timezone.now().isoformat(),
        }

        if success:
            logger.info(f"[TASK_send_welcome_email] Successfully sent welcome email to {user.email}")
        else:
            logger.warning(f"[TASK_send_welcome_email] Failed to send welcome email to {user.email}")

        return result

    except User.DoesNotExist:
        error_msg = f"[TASK_send_welcome_email] User with ID {user_id} not found"
        logger.error(error_msg)
        return {
            "user_id": user_id,
            "success": False,
            "error": "User not found",
            "timestamp": timezone.now().isoformat(),
        }
    except Exception as e:
        error_msg = f"[TASK_send_welcome_email] Error for user {user_id}: {str(e)}"
        logger.error(error_msg)
        raise  # Re-raise for retry mechanism


@dramatiq.actor(queue_name="onboarding_emails", max_retries=3, time_limit=60000)
@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
)
def send_first_component_sbom_email_task(user_id: int) -> dict:
    """
    Send first component & SBOM reminder email to a user.

    This email adapts based on user progress:
    - Component focus if no components created
    - SBOM focus if components exist but no SBOMs

    Args:
        user_id: ID of the user to send reminder email to

    Returns:
        Dictionary with task results
    """
    try:
        user = User.objects.get(id=user_id)
        logger.info(f"[TASK_send_first_component_sbom] Starting for user {user.email}")

        success = OnboardingEmailService.send_first_component_sbom_email(user)

        result = {
            "user_id": user_id,
            "user_email": user.email,
            "success": success,
            "timestamp": timezone.now().isoformat(),
        }

        if success:
            logger.info(f"[TASK_send_first_component_sbom] Successfully sent reminder to {user.email}")
        else:
            logger.info(f"[TASK_send_first_component_sbom] Reminder not needed for {user.email}")

        return result

    except User.DoesNotExist:
        error_msg = f"[TASK_send_first_component_sbom] User with ID {user_id} not found"
        logger.error(error_msg)
        return {
            "user_id": user_id,
            "success": False,
            "error": "User not found",
            "timestamp": timezone.now().isoformat(),
        }
    except Exception as e:
        error_msg = f"[TASK_send_first_component_sbom] Error for user {user_id}: {str(e)}"
        logger.error(error_msg)
        raise  # Re-raise for retry mechanism


@dramatiq.actor(queue_name="onboarding_emails", max_retries=1, time_limit=300000)
def process_first_component_sbom_reminders_batch_task() -> dict:
    """
    Process first component & SBOM reminders for all eligible users.

    This task finds all users who should receive either component creation
    or SBOM upload reminders and queues individual email tasks for them.

    Returns:
        Dictionary with batch processing results
    """
    try:
        logger.info("[TASK_process_first_component_sbom_reminders] Starting batch processing")

        eligible_users = OnboardingEmailService.get_users_for_first_component_sbom_reminder()
        user_count = eligible_users.count()

        logger.info(f"[TASK_process_first_component_sbom_reminders] Found {user_count} eligible users")

        queued_tasks = 0
        for user in eligible_users:
            try:
                # Queue individual email task
                send_first_component_sbom_email_task.send(user.id)
                queued_tasks += 1
                logger.debug(f"[TASK_process_first_component_sbom_reminders] Queued task for user {user.email}")
            except Exception as e:
                logger.error(
                    f"[TASK_process_first_component_sbom_reminders] Failed to queue task for user {user.id}: {e}"
                )

        result = {
            "eligible_users": user_count,
            "queued_tasks": queued_tasks,
            "timestamp": timezone.now().isoformat(),
        }

        logger.info(
            f"[TASK_process_first_component_sbom_reminders] Completed: {queued_tasks}/{user_count} tasks queued"
        )
        return result

    except Exception as e:
        error_msg = f"[TASK_process_first_component_sbom_reminders] Batch processing error: {str(e)}"
        logger.error(error_msg)
        raise


@dramatiq.actor(queue_name="onboarding_emails", max_retries=1, time_limit=600000)
def process_all_onboarding_reminders_task() -> dict:
    """
    Process all onboarding reminder emails.

    This is a master task that processes first component/SBOM reminders.
    It's designed to be run on a schedule (e.g., daily via cron or periodic task).

    Returns:
        Dictionary with overall processing results
    """
    try:
        logger.info("[TASK_process_all_onboarding_reminders] Starting comprehensive onboarding email processing")

        # Process first component/SBOM reminders
        reminder_result = process_first_component_sbom_reminders_batch_task.send_with_options(args=(), delay=0)

        result = {
            "first_component_sbom_task_id": reminder_result.message_id,
            "timestamp": timezone.now().isoformat(),
        }

        logger.info("[TASK_process_all_onboarding_reminders] Successfully queued all reminder processing tasks")
        return result

    except Exception as e:
        error_msg = f"[TASK_process_all_onboarding_reminders] Error: {str(e)}"
        logger.error(error_msg)
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
    logger.info(f"Queueing welcome email for user {user.email}")
    result = send_welcome_email_task.send(user.id)
    return result.message_id


def queue_first_component_sbom_reminder(user) -> str:
    """
    Queue a first component/SBOM reminder email task for a user.

    Args:
        user: User instance

    Returns:
        Task message ID
    """
    logger.info(f"Queueing first component/SBOM reminder for user {user.email}")
    result = send_first_component_sbom_email_task.send(user.id)
    return result.message_id
