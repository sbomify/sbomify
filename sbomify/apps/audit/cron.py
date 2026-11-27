"""Periodic tasks for the audit log."""

from __future__ import annotations

import dramatiq
from dramatiq_crontab import cron

from sbomify.logging import getLogger

logger = getLogger(__name__)


@cron("30 3 * * *")  # type: ignore[untyped-decorator]  # Daily at 3:30 AM UTC
@dramatiq.actor(queue_name="audit_retention_cron", max_retries=1, time_limit=1800000)
def purge_expired_audit_events() -> None:
    """Delete audit events past their workspace's retention window."""
    from .services import purge_expired

    deleted = purge_expired()
    logger.info("audit_retention_purge deleted=%d", deleted)
