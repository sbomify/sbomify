"""Whether a component's SBOM is still current.

A component whose newest SBOM is fourteen months old looks identical today to
one updated yesterday, and CRA support-period obligations expect documentation
kept current.

Two decisions worth stating, because both went the opposite way to the issue's
first sketch:

**The window lives on the workspace, not the product.** A component can belong
to several products (eight already do in a single dev database), so a
per-product default has no single answer for those components: three products
could each declare a different window over the same component. The workspace is
the one unambiguous owner, with a per-component override for the exceptions.

**Only ``bom_type="sbom"`` counts.** A component also holds CBOMs, HBOMs, VEX
documents and plain documents, and those move on their own cadence. If any
upload reset the clock, a component with a fourteen-month-old SBOM and a VEX
uploaded yesterday would read as fresh, which inverts the point of the feature.
A component whose only artifact is an HBOM therefore has no freshness state at
all — hardware inventories carry no software support period to keep current.

Nothing is stored: freshness is arithmetic over the newest SBOM's timestamp, so
there is no state to keep in step with uploads. With no window configured a
component has no freshness state at all, which keeps the feature opt-in rather
than badging every workspace the day it ships.
"""

from __future__ import annotations

from typing import Any

from django.db.models import OuterRef, QuerySet, Subquery
from django.utils import timezone


def window_days(component: Any) -> int | None:
    """The freshness window that applies, or None when no policy is set."""
    # `is not None` rather than truthiness: the field is a PositiveIntegerField,
    # so 0 is storable and means "expires immediately". Treating it as unset
    # would silently ignore a configured value and make an override of 0
    # fail to round-trip.
    override = getattr(component, "sbom_freshness_days", None)
    if override is not None:
        return int(override)

    team = getattr(component, "team", None)
    default = getattr(team, "sbom_freshness_days", None) if team is not None else None
    return int(default) if default is not None else None


def freshness_state(latest_sbom_at: Any, window: int | None) -> dict[str, Any] | None:
    """``{"expires_in_days", "is_stale", "window_days"}``, or None when unknowable.

    None covers both "no policy configured" and "no SBOM yet": neither is a
    stale component, and reporting one as stale would be a false alarm on a
    component nobody has uploaded to.
    """
    if window is None or latest_sbom_at is None:
        return None

    remaining_days = window - (timezone.now() - latest_sbom_at).total_seconds() / 86400
    # Staleness compares the exact remainder, not the rounded one: an SBOM an
    # hour past its window is stale even though it displays as "0 days".
    # Rounding only the display keeps a ten-day-old SBOM on a ninety-day window
    # reading as 80 rather than 79, which flooring would give for the
    # microseconds that elapse between the timestamp and now().
    return {
        "window_days": window,
        "expires_in_days": round(remaining_days),
        "is_stale": remaining_days < 0,
    }


def with_latest_sbom(queryset: QuerySet[Any]) -> QuerySet[Any]:
    """Annotate ``latest_sbom_at`` so a list view needs no per-row query.

    The component list is a hot path; fetching the newest SBOM per row in Python
    is the N+1 this exists to avoid.
    """
    from sbomify.apps.sboms.models import SBOM

    newest = (
        SBOM.objects.filter(component_id=OuterRef("pk"), bom_type=SBOM.BomType.SBOM)
        .order_by("-created_at")
        .values("created_at")[:1]
    )
    annotated: QuerySet[Any] = queryset.annotate(latest_sbom_at=Subquery(newest))
    return annotated


def component_freshness(component: Any) -> dict[str, Any] | None:
    """Freshness for one component, using ``latest_sbom_at`` when annotated."""
    latest = getattr(component, "latest_sbom_at", None)
    if latest is None and not hasattr(component, "latest_sbom_at"):
        from sbomify.apps.sboms.models import SBOM

        latest = (
            SBOM.objects.filter(component=component, bom_type=SBOM.BomType.SBOM)
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
    return freshness_state(latest, window_days(component))
