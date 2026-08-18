"""SBOM freshness: the window, the derived state, and the two design choices.

Both choices went against the issue's first sketch, so they are pinned here:
the window lives on the workspace rather than the product (a component can
belong to several products), and only ``bom_type="sbom"`` resets the clock (a
recent VEX must not make a stale SBOM look fresh).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.sboms.freshness import (
    component_freshness,
    freshness_state,
    window_days,
    with_latest_sbom,
)
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_component,
    sample_product,
)

pytestmark = pytest.mark.django_db


def _sbom(component, *, days_ago: int, bom_type: str = "sbom", name: str = "bom"):
    # The uniqueness key is (component, version, format, qualifiers, bom_type),
    # so two SBOMs on one component need distinct versions, not distinct names.
    sbom = SBOM.objects.create(
        component=component, name=name, version=f"1.0.{days_ago}", format="cyclonedx", bom_type=bom_type
    )
    # created_at is auto_now_add, so it has to be moved after the fact.
    SBOM.objects.filter(pk=sbom.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    sbom.refresh_from_db()
    return sbom


class TestWindow:
    def test_no_policy_anywhere_means_none(self, sample_component):  # noqa: F811
        assert window_days(sample_component) is None

    def test_the_workspace_default_applies(self, sample_component):  # noqa: F811
        sample_component.team.sbom_freshness_days = 90
        sample_component.team.save()

        assert window_days(sample_component) == 90

    def test_a_component_override_wins(self, sample_component):  # noqa: F811
        sample_component.team.sbom_freshness_days = 90
        sample_component.team.save()
        sample_component.sbom_freshness_days = 30

        assert window_days(sample_component) == 30

    def test_the_window_lives_on_the_workspace_not_the_product(self, sample_component, sample_product):  # noqa: F811
        """A component can belong to several products, so a per-product default
        would have no single answer for it."""
        assert not hasattr(sample_product, "sbom_freshness_days")


class TestState:
    def test_no_window_means_no_state(self):
        assert freshness_state(timezone.now(), None) is None

    def test_no_sbom_means_no_state(self):
        """A component nobody has uploaded to is not stale; calling it stale
        would be a false alarm."""
        assert freshness_state(None, 90) is None

    def test_a_recent_sbom_is_fresh(self):
        state = freshness_state(timezone.now() - timedelta(days=10), 90)

        assert state["is_stale"] is False
        assert state["expires_in_days"] == 80

    def test_an_old_sbom_is_stale(self):
        state = freshness_state(timezone.now() - timedelta(days=120), 90)

        assert state["is_stale"] is True
        assert state["expires_in_days"] == -30

    def test_just_past_the_window_reads_expired(self):
        """Staleness compares the exact remainder, so an hour past the window is
        stale even though it displays as 0 days."""
        state = freshness_state(timezone.now() - timedelta(days=90, hours=1), 90)

        assert state["is_stale"] is True

    def test_the_window_is_reported_back(self):
        assert freshness_state(timezone.now(), 30)["window_days"] == 30


class TestOnlySbomsCount:
    def test_a_recent_vex_does_not_refresh_a_stale_sbom(self, sample_component):  # noqa: F811
        """The whole point of the feature: any-artifact freshness would read
        this component as current."""
        sample_component.team.sbom_freshness_days = 90
        sample_component.team.save()
        _sbom(sample_component, days_ago=200, name="old-sbom")
        _sbom(sample_component, days_ago=1, bom_type="vex", name="fresh-vex")

        state = component_freshness(sample_component)

        assert state["is_stale"] is True

    def test_a_recent_sbom_does_refresh(self, sample_component):  # noqa: F811
        sample_component.team.sbom_freshness_days = 90
        sample_component.team.save()
        _sbom(sample_component, days_ago=200, name="old-sbom")
        _sbom(sample_component, days_ago=2, name="new-sbom")

        assert component_freshness(sample_component)["is_stale"] is False


class TestListAnnotation:
    def test_the_annotation_avoids_a_per_row_query(self, sample_component, django_assert_num_queries):  # noqa: F811
        """The component list is a hot path; this is the N+1 it exists to avoid."""
        sample_component.team.sbom_freshness_days = 90
        sample_component.team.save()
        _sbom(sample_component, days_ago=5)

        queryset = with_latest_sbom(Component.objects.filter(pk=sample_component.pk).select_related("team"))

        with django_assert_num_queries(1):
            rows = list(queryset)
            states = [component_freshness(row) for row in rows]

        assert states[0]["is_stale"] is False

    def test_a_component_with_no_sbom_annotates_to_none(self, sample_component):  # noqa: F811
        queryset = with_latest_sbom(Component.objects.filter(pk=sample_component.pk))

        assert queryset.first().latest_sbom_at is None


class TestZeroWindow:
    """0 is storable in a PositiveIntegerField, so it has to mean something
    definite rather than being swallowed as "unset"."""

    def test_a_zero_workspace_window_is_a_real_policy(self, sample_component):  # noqa: F811
        sample_component.team.sbom_freshness_days = 0
        sample_component.team.save()

        assert window_days(sample_component) == 0

    def test_a_zero_component_override_beats_a_set_workspace_default(self, sample_component):  # noqa: F811
        sample_component.team.sbom_freshness_days = 90
        sample_component.team.save()
        sample_component.sbom_freshness_days = 0

        assert window_days(sample_component) == 0

    def test_a_zero_window_expires_immediately(self):
        state = freshness_state(timezone.now() - timedelta(hours=1), 0)

        assert state["is_stale"] is True
