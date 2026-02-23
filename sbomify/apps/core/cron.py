"""Periodic tasks for core app."""

import dramatiq
from dramatiq_crontab import cron

from sbomify.logging import getLogger

logger = getLogger(__name__)


@cron("0 3 * * *")  # Daily at 3:00 AM UTC
@dramatiq.actor(queue_name="user_purge_cron", max_retries=1, time_limit=300000)
def purge_soft_deleted_users():
    """
    Permanently delete users whose soft-delete grace period has expired.

    Runs daily. Finds users where is_active=False, deleted_at is set,
    and deleted_at is older than SOFT_DELETE_GRACE_DAYS (14 days).
    """
    from datetime import timedelta

    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from sbomify.apps.core.services.account_deletion import SOFT_DELETE_GRACE_DAYS, hard_delete_user

    User = get_user_model()

    cutoff = timezone.now() - timedelta(days=SOFT_DELETE_GRACE_DAYS)
    users_to_purge = User.objects.filter(
        is_active=False,
        deleted_at__isnull=False,
        deleted_at__lte=cutoff,
    )

    count = users_to_purge.count()
    if count == 0:
        logger.info("No soft-deleted users to purge")
        return

    logger.info("Found %d soft-deleted users past grace period", count)

    purged = 0
    errors = 0
    for user in users_to_purge:
        try:
            if hard_delete_user(user):
                purged += 1
            else:
                errors += 1
        except Exception:
            logger.exception("Failed to hard-delete user %s", user.id)
            errors += 1

    logger.info("Purge complete: purged=%d, errors=%d", purged, errors)
