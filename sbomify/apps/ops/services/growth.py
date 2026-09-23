"""Signups over time, and how far new people get.

Two things the old dashboard got wrong live here. The trend dropped days with
no signups instead of plotting them flat, so a quiet week compressed into the
line and read as steady activity. And the funnel divided ``OnboardingStatus``
rows by the total user count, which are different populations: bots never get
a status row, so every completion rate read low by however many publishing
identities existed.

Both sides of the funnel are now the same population, ``people()``. Counting
status rows on either side is the same category error in the other direction,
because a status row is not guaranteed for a real person either: see
``onboarding.tests.test_missing_status_backfill`` for four live accounts that
have none.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from sbomify.apps.onboarding.models import OnboardingStatus

from .cache import panel
from .populations import people

CACHE_TTL_SECONDS = 600


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


def _build_signups_by_day(days: int) -> list[DailyCount]:
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


def _build_activation_funnel() -> list[ActivationStep]:
    """How far signups get, measured against the population that signed up.

    The denominator is ``people()``: everyone with a live account who is not a
    publishing identity. It is deliberately not the count of
    ``OnboardingStatus`` rows, even though every step above it is one.

    The status row is created by a signal on user creation, so anyone who
    predates that signal, or whose creation took a path around it, has none.
    That is not hypothetical: the sequence processor was stepping over four
    such owners on every run until the row was backfilled. Counting rows here
    would drop those people out of the denominator *and* out of "Signed up",
    which quietly flatters every rate below.

    Bots are excluded because ``people()`` excludes them, not because they
    happen to lack a status row.

    The last step says BOM rather than artifact, deliberately. Every step
    above the denominator is an ``OnboardingStatus`` flag, and
    ``has_uploaded_sbom`` is set by a ``post_save`` on the BOM table only:
    a document upload never touches it. ``populations.artifact_count`` counts
    documents, so calling this step "artifact" would put two different
    definitions of the word on one page. The narrow name is the honest one
    until the flag itself covers both, which is a change to the onboarding
    app rather than to this panel.

    The flag is also only ever set for a workspace's primary owner, so this
    step under-counts anyone else in a publishing workspace.
    """
    signed_up = people().count()
    statuses = OnboardingStatus.objects.filter(user__in=people())

    steps = (
        ("Signed up", signed_up),
        ("Finished the wizard", statuses.filter(has_completed_wizard=True).count()),
        ("Created a component", statuses.filter(has_created_component=True).count()),
        ("Uploaded a BOM", statuses.filter(has_uploaded_sbom=True).count()),
    )

    return [
        ActivationStep(
            label=label,
            count=count,
            percent_of_signups=round(100 * count / signed_up, 1) if signed_up else 0.0,
        )
        for label, count in steps
    ]


def signups_by_day(days: int = 30, *, refresh: bool = False) -> list[DailyCount]:
    """New people per day, with every day in the window present."""
    return panel(f"signups:{days}", CACHE_TTL_SECONDS, lambda: _build_signups_by_day(days), refresh=refresh)


def activation_funnel(*, refresh: bool = False) -> list[ActivationStep]:
    """How far signups get, measured against the population that can progress."""
    return panel("activation", CACHE_TTL_SECONDS, _build_activation_funnel, refresh=refresh)
