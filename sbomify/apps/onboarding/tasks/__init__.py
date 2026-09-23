"""
Dramatiq tasks for onboarding email processing.
"""

from __future__ import annotations

import datetime
from typing import Any

import dramatiq
from django.contrib.auth import get_user_model

from sbomify.logging import getLogger
from sbomify.task_utils import record_task_breadcrumb

from ..services import OnboardingEmailService, TransientEmailError

User = get_user_model()
logger = getLogger(__name__)


def _report_send_failure(log_prefix: str, task_name: str, user_id: int, exc: Exception) -> None:
    """Record a failed send at the level its recoverability deserves.

    Sentry's logging integration is wired with ``event_level=ERROR``, so a
    transient failure logged at error here would raise an issue on every one
    of the four attempts before the retry that fixes it. The attempt that runs
    out of retries still reports: the exception leaves the actor unhandled and
    dramatiq's integration sends it once, which is the one worth reading.
    """
    if isinstance(exc, TransientEmailError):
        # "Retryable", not "will retry": the attempt that exhausts the budget
        # reaches this line too, and a log promising another try when there is
        # none sends whoever reads it looking for a delivery that never comes.
        logger.warning("%s Retryable failure for user %s: %s", log_prefix, user_id, exc.__cause__ or exc)
        record_task_breadcrumb(task_name, "retryable_error", level="warning", data={"user_id": user_id})
    else:
        logger.error("%s Error for user %s: %s", log_prefix, user_id, exc)
        record_task_breadcrumb(task_name, "error", level="error", data={"error": str(exc)})


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
        _report_send_failure("[TASK_send_welcome_email]", "send_welcome_email_task", user_id, e)
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
        _report_send_failure("[TASK_send_quick_start]", "send_quick_start_email_task", user_id, e)
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
        _report_send_failure("[TASK_send_first_component]", "send_first_component_email_task", user_id, e)
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
        _report_send_failure("[TASK_send_first_sbom]", "send_first_sbom_email_task", user_id, e)
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
        _report_send_failure("[TASK_send_collaboration]", "send_collaboration_email_task", user_id, e)
        raise


@dramatiq.actor(queue_name="onboarding_emails", max_retries=1, time_limit=300000)
def process_onboarding_sequence_batch_task() -> None:
    """
    Process all onboarding sequence emails for eligible users.

    Finds users eligible for each email type and queues individual tasks.
    """
    from ..models import OnboardingEmail as OE

    task_map: dict[str, Any] = {
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
    Process all onboarding reminder emails (the 4-stage drip sequence).

    Designed to be run on a schedule (e.g., daily via cron or periodic task).
    Fans out to ``process_onboarding_sequence_batch_task``, which queues
    quick-start / first-component / first-sbom / collaboration emails for
    users at the right point in their drip clock, and to
    ``requeue_missed_welcome_emails_task``, which is the welcome email's only
    second chance: that one is signal-driven via ``queue_welcome_email`` on
    user creation, so a send that failed has nothing else to pick it up.
    """
    try:
        logger.info("[TASK_process_all_onboarding_reminders] Starting onboarding email processing")
        process_onboarding_sequence_batch_task.send_with_options(args=(), delay=0)
        requeue_missed_welcome_emails_task.send_with_options(args=(), delay=0)
        logger.info("[TASK_process_all_onboarding_reminders] Successfully queued sequence processing")

    except Exception as e:
        logger.error("[TASK_process_all_onboarding_reminders] Error: %s", e)
        raise


#: How far back the welcome sweep looks, measured from ``User.date_joined``.
#: The welcome email is sent within seconds of signup, so anything that is
#: going to fail has failed long before this. The bound is what keeps the sweep
#: a recovery rather than a backfill: without it, its first run would mail every
#: account that predates the onboarding sequence entirely.
WELCOME_RECOVERY_WINDOW_DAYS = 7


@dramatiq.actor(queue_name="onboarding_emails", max_retries=1, time_limit=300000)
def requeue_missed_welcome_emails_task() -> None:
    """Re-queue welcome emails for recent signups that never got one.

    Everything else in onboarding gets another pass from the daily batch, so a
    broken template or an exhausted retry budget costs a delay rather than the
    message. The welcome email had no such path: it is queued once, by a signal
    on user creation, and a send that failed was simply gone.

    ``welcome_email_sent`` is set only on a successful send, so it is the whole
    of the eligibility test, along with its own absence: a user with no
    ``OnboardingStatus`` row at all is the case where the welcome is most
    certainly missing, because the signal that creates the row is the signal
    that queues the email. The service still applies its own gates — bot
    identities, deactivated or soft-deleted accounts, and an address already
    refused — so this only reaches users a send would legitimately go to, and it
    is the right place for those rules to live rather than duplicated into this
    query. The liveness pair is repeated here anyway, to avoid queueing a task
    per deleted account for the service to throw away.

    The drip opt-out is deliberately *not* one of them. It covers the scheduled
    sequence; the welcome email confirms an account the user just created, so
    it stays transactional and ``send_welcome_email`` does not check the flag.
    Filtering on it here would suppress a welcome that failed before the opt-out
    and could then never be sent, which is stricter than the send path itself.

    The window is measured on the account, not on its status row. A status row
    is created by ``get_or_create`` from the component and SBOM tracking paths
    too, so a long-lived user can acquire one this week; keying the cutoff to
    that would mail someone who signed up years ago. ``date_joined`` is the
    signup, and the welcome email is sent seconds after it.

    Not restricted to workspace owners either: the post-save signal queues a
    welcome for every human user, so an owner-only sweep would leave a failed
    send lost for exactly the accounts that are not primary owners.
    """
    from django.db.models import Q
    from django.utils import timezone

    from sbomify.apps.oidc.services import BOT_EMAIL_DOMAIN, BOT_USERNAME_PREFIX

    from ..models import OnboardingEmail
    from ..services import refused_at_current_address

    cutoff = timezone.now() - datetime.timedelta(days=WELCOME_RECOVERY_WINDOW_DAYS)
    # A refused welcome leaves welcome_email_sent false forever, so without
    # this the sweep re-queues every permanently refused address daily for the
    # length of the window. The service would refuse each one, but only after a
    # task had been queued and its template rendered.
    refused = OnboardingEmail.objects.filter(email_type=OnboardingEmail.EmailType.WELCOME).filter(
        refused_at_current_address()
    )
    # Driven from the user, not from OnboardingStatus. The post-save signal
    # creates that row and queues the welcome, so a failure there leaves a user
    # with neither — invisible to a query that starts at the status table, and
    # the one case where the welcome is most certainly missing.
    # ``send_welcome_email`` calls ``get_or_create`` on it, so the row appears
    # when the send runs.
    missed = (
        User.objects.filter(date_joined__gte=cutoff, is_active=True, deleted_at__isnull=True)
        .filter(Q(onboarding_status__isnull=True) | Q(onboarding_status__welcome_email_sent=False))
        .exclude(username__startswith=BOT_USERNAME_PREFIX)
        .exclude(email__iendswith=f"@{BOT_EMAIL_DOMAIN}")
        .exclude(id__in=refused.values("user_id"))
        .values_list("id", flat=True)
    )

    queued = 0
    for user_id in missed:
        send_welcome_email_task.send_with_options(args=(user_id,), delay=0)
        queued += 1

    if queued:
        logger.info("[TASK_requeue_missed_welcome] Re-queued %d welcome email(s)", queued)


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
