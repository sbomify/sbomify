"""The overview panel: is the business healthy right now.

Each panel owns its own cache entry rather than sharing one blob, so a slow
or stale panel cannot hold up the rest of the page and the refresh interval
can match how fast the underlying number actually moves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone

from sbomify.apps.billing.services.workspace_status import (
    past_due_workspaces,
    paying_workspaces,
    trialing_workspaces,
)
from sbomify.apps.core.services.results import ServiceResult

from .growth import ActivationStep, DailyCount, activation_funnel, signups_by_day
from .populations import artifacts, people, workspaces
from .revenue import RecurringRevenue, recurring_revenue

logger = logging.getLogger(__name__)

CACHE_KEY = "ops:overview"
CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class PlanCount:
    """How many workspaces sit on one plan."""

    plan: str
    count: int


@dataclass(frozen=True)
class Overview:
    """Everything the overview page renders."""

    revenue: RecurringRevenue
    paying_workspaces: int
    trialing_workspaces: int
    past_due_workspaces: int

    people: int
    new_people_30d: int
    active_workspaces_7d: int
    total_workspaces: int

    artifacts_total: int
    artifacts_30d: int

    signups: list[DailyCount]
    funnel: list[ActivationStep]
    plans: list[PlanCount]

    generated_at: str


def _build_overview() -> Overview:
    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    # A workspace is active if something was published into it, not if someone
    # signed in. With SSO and long-lived sessions a daily user can go months
    # without a fresh login, which is what made the old "active users" number
    # meaningless.
    active_workspaces = workspaces().filter(component__sbom__created_at__gte=seven_days_ago).distinct().count()

    plans = [
        PlanCount(plan=row["billing_plan"] or "none", count=row["count"])
        for row in workspaces().values("billing_plan").annotate(count=Count("id")).order_by("-count")
    ]

    return Overview(
        revenue=recurring_revenue(),
        paying_workspaces=paying_workspaces().count(),
        trialing_workspaces=trialing_workspaces().count(),
        past_due_workspaces=past_due_workspaces().count(),
        people=people().count(),
        new_people_30d=people().filter(date_joined__gte=thirty_days_ago).count(),
        active_workspaces_7d=active_workspaces,
        total_workspaces=workspaces().count(),
        artifacts_total=artifacts().count(),
        artifacts_30d=artifacts().filter(created_at__gte=thirty_days_ago).count(),
        signups=signups_by_day(30),
        funnel=activation_funnel(),
        plans=plans,
        generated_at=now.isoformat(),
    )


def get_overview(*, refresh: bool = False) -> ServiceResult[Overview]:
    """Build the overview panel, cached.

    Returns a failure rather than a dict of zeroes when something breaks. The
    old dashboard hand-maintained a parallel dict of fallback values, which
    drifted from the real one and turned an outage into a page of plausible
    zeroes.
    """
    if not refresh:
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            return ServiceResult.success(cached)

    try:
        overview = _build_overview()
    except Exception:
        logger.exception("Failed to build the ops overview panel")
        return ServiceResult.failure("Could not load these numbers. The error has been logged.", status_code=500)

    cache.set(CACHE_KEY, overview, CACHE_TTL_SECONDS)
    return ServiceResult.success(overview)
