"""The overview page: is the business healthy right now.

The page is a composition of panels, and each panel caches under its own key
with its own lifetime (see ``cache.py``). Recurring revenue is the expensive
one and moves slowly; the counts are cheap and wanted fresh. Nothing here
caches the assembled page, so one panel going stale refreshes that panel and
leaves the rest alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from sbomify.apps.billing.services.workspace_status import (
    past_due_workspaces,
    paying_workspaces,
    trialing_workspaces,
)
from sbomify.apps.core.services.results import ServiceResult

from .cache import panel
from .growth import ActivationStep, DailyCount, activation_funnel, signups_by_day
from .populations import artifacts, people, workspaces
from .revenue import RecurringRevenue, recurring_revenue

logger = logging.getLogger(__name__)

COUNTS_CACHE_TTL_SECONDS = 300
"""Five minutes. These are single counting queries and are wanted fresh."""


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


@dataclass(frozen=True)
class Counts:
    """The cheap counting queries, which share a lifetime because they share a cost."""

    paying_workspaces: int
    trialing_workspaces: int
    past_due_workspaces: int
    people: int
    new_people_30d: int
    active_workspaces_7d: int
    total_workspaces: int
    artifacts_total: int
    artifacts_30d: int
    plans: list[PlanCount]


def _build_counts() -> Counts:
    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    return Counts(
        paying_workspaces=paying_workspaces().count(),
        trialing_workspaces=trialing_workspaces().count(),
        past_due_workspaces=past_due_workspaces().count(),
        people=people().count(),
        new_people_30d=people().filter(date_joined__gte=thirty_days_ago).count(),
        # A workspace is active if something was published into it, not if
        # someone signed in. With SSO and long-lived sessions a daily user can
        # go months without a fresh login, which is what made the old "active
        # users" number meaningless.
        active_workspaces_7d=workspaces().filter(component__sbom__created_at__gte=seven_days_ago).distinct().count(),
        total_workspaces=workspaces().count(),
        artifacts_total=artifacts().count(),
        artifacts_30d=artifacts().filter(created_at__gte=thirty_days_ago).count(),
        plans=[
            PlanCount(plan=row["billing_plan"] or "none", count=row["count"])
            for row in workspaces().values("billing_plan").annotate(count=Count("id")).order_by("-count")
        ],
    )


def _assemble(*, refresh: bool) -> Overview:
    counts = panel("counts", COUNTS_CACHE_TTL_SECONDS, _build_counts, refresh=refresh)

    return Overview(
        revenue=recurring_revenue(refresh=refresh),
        paying_workspaces=counts.paying_workspaces,
        trialing_workspaces=counts.trialing_workspaces,
        past_due_workspaces=counts.past_due_workspaces,
        people=counts.people,
        new_people_30d=counts.new_people_30d,
        active_workspaces_7d=counts.active_workspaces_7d,
        total_workspaces=counts.total_workspaces,
        artifacts_total=counts.artifacts_total,
        artifacts_30d=counts.artifacts_30d,
        signups=signups_by_day(30, refresh=refresh),
        funnel=activation_funnel(refresh=refresh),
        plans=counts.plans,
        generated_at=timezone.now().isoformat(),
    )


def get_overview(*, refresh: bool = False) -> ServiceResult[Overview]:
    """Assemble the overview page from its panels.

    Returns a failure rather than a dict of zeroes when something breaks. The
    old dashboard hand-maintained a parallel dict of fallback values, which
    drifted from the real one and turned an outage into a page of plausible
    zeroes.
    """
    try:
        return ServiceResult.success(_assemble(refresh=refresh))
    except Exception:
        logger.exception("Failed to build the ops overview page")
        return ServiceResult.failure("Could not load these numbers. The error has been logged.", status_code=500)
