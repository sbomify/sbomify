"""Background tasks for core app."""

from __future__ import annotations

from typing import Any

import dramatiq
from django.core.cache import cache
from django.db import transaction

from sbomify.logging import getLogger

logger = getLogger(__name__)

#: Set while a usage report is queued, so a burst of changes sends one report.
USAGE_REPORT_PENDING_KEY = "installation_usage_report_pending"
#: How long a change waits before the report goes out. Every change made in
#: that window lands in the same report, since the counts are read on send.
USAGE_REPORT_DELAY_MS = 5 * 60 * 1000
#: Outlives the delay, so a report a worker never runs does not block the next one forever.
USAGE_REPORT_PENDING_TIMEOUT = 30 * 60


def schedule_installation_usage_report() -> None:
    """Queue a usage report once the current transaction commits, unless one is already queued."""
    from sbomify.apps.core import posthog_service

    if not posthog_service.is_enabled():
        return

    def _send() -> None:
        try:
            if cache.add(USAGE_REPORT_PENDING_KEY, True, USAGE_REPORT_PENDING_TIMEOUT):
                report_installation_usage.send_with_options(delay=USAGE_REPORT_DELAY_MS)
        except Exception:
            logger.exception("Failed to queue the installation usage report")

    transaction.on_commit(_send)


@dramatiq.actor(queue_name="installation_usage", max_retries=1, time_limit=300000)
def report_installation_usage() -> Any:
    """Send PostHog the size of this installation: workspaces, products, components."""
    from sbomify.apps.core import posthog_service
    from sbomify.apps.core.analytics import events
    from sbomify.apps.plugins.utils import get_sbomify_version
    from sbomify.apps.sboms.models import Component, Product
    from sbomify.apps.teams.models import Workspace

    # Cleared before counting, so a change made while this runs queues the next report.
    cache.delete(USAGE_REPORT_PENDING_KEY)

    if not posthog_service.is_enabled():
        return

    installation_id = posthog_service.get_installation_id()
    if not installation_id:
        logger.warning("Skipping installation usage report: no installation id")
        return

    properties = {
        "workspace_count": Workspace.objects.count(),
        "product_count": Product.objects.count(),
        "component_count": Component.objects.count(),
        "sbomify_version": get_sbomify_version(),
    }
    posthog_service.capture(
        installation_id,
        events.INSTALLATION_USAGE_REPORTED,
        properties,
        groups={"installation": installation_id},
    )
    logger.info("Installation usage reported: %s", properties)
