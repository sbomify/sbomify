"""Signups over time, and how far new people get.

Two things the old dashboard got wrong live here. The trend dropped days with
no signups instead of plotting them flat, so a quiet week compressed into the
line and read as steady activity. And the funnel divided ``OnboardingStatus``
rows by the total user count, which are different populations: bots never get
a status row, so every completion rate read low by however many publishing
identities existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from sbomify.apps.onboarding.models import OnboardingStatus

from .populations import people


@dataclass(frozen=True)
class DailyCount:
    """One point on a daily series."""

    day: date
    count: int


@dataclass(frozen=True)
class ActivationStep:
    """One step of the activation funnel."""

    label: str
    count: int
    percent_of_signups: float
    """Percentage of the same population that reached this step, 0 to 100."""


def signups_by_day(days: int = 30) -> list[DailyCount]:
    """New people per day, with every day in the window present.

    Days with no signups are returned as zero rather than omitted. A chart
    cannot tell a missing day from a day that did not happen, so leaving them
    out lets a flat line masquerade as a busy one.

    Dates are returned as dates. Formatting is the template's job.
    """
    today = timezone.localdate()
    first_day = today - timedelta(days=days - 1)

    counted = {
        row["day"]: row["count"]
        for row in people()
        .filter(date_joined__date__gte=first_day)
        .annotate(day=TruncDate("date_joined"))
        .values("day")
        .annotate(count=Count("id"))
    }

    return [
        DailyCount(day=first_day + timedelta(days=offset), count=counted.get(first_day + timedelta(days=offset), 0))
        for offset in range(days)
    ]


def activation_funnel() -> list[ActivationStep]:
    """How far signups get, measured against the population that can progress.

    The denominator is people with an ``OnboardingStatus`` row, not every User
    row. A synthetic bot identity has no status row by design, so including it
    in the denominator would permanently understate every rate below.
    """
    statuses = OnboardingStatus.objects.filter(user__in=people())
    signed_up = statuses.count()

    steps = (
        ("Signed up", signed_up),
        ("Finished the wizard", statuses.filter(has_completed_wizard=True).count()),
        ("Created a component", statuses.filter(has_created_component=True).count()),
        ("Uploaded an artifact", statuses.filter(has_uploaded_sbom=True).count()),
    )

    return [
        ActivationStep(
            label=label,
            count=count,
            percent_of_signups=round(100 * count / signed_up, 1) if signed_up else 0.0,
        )
        for label, count in steps
    ]
