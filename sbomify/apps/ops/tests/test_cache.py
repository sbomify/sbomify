"""Panels cache on their own terms, which is the point of splitting them."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from sbomify.apps.ops.services import growth, revenue
from sbomify.apps.ops.services.cache import KEY_PREFIX, panel


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()
    yield
    cache.clear()


class TestPanelCache:
    def test_a_panel_is_built_once_and_then_served_from_its_entry(self):
        calls = []

        def build():
            calls.append(1)
            return "value"

        assert panel("demo", 60, build) == "value"
        assert panel("demo", 60, build) == "value"
        assert len(calls) == 1

    def test_refresh_rebuilds_that_panel(self):
        calls = []

        def build():
            calls.append(1)
            return len(calls)

        panel("demo", 60, build)
        assert panel("demo", 60, build, refresh=True) == 2

    def test_panels_do_not_share_an_entry(self):
        """One panel expiring must not take the rest of the page with it."""
        panel("first", 60, lambda: "a")
        panel("second", 60, lambda: "b")

        cache.delete(f"{KEY_PREFIX}:first")

        assert cache.get(f"{KEY_PREFIX}:second") == "b"

    def test_a_falsy_value_is_still_cached_correctly(self):
        calls = []

        def build():
            calls.append(1)
            return 0

        assert panel("zero", 60, build) == 0
        assert panel("zero", 60, build) == 0
        # A zero count is a real answer. Caching it as a miss would rebuild the
        # panel on every request for an install with nothing in it yet.
        assert len(calls) == 1


class TestPanelsHaveTheirOwnLifetimes:
    def test_revenue_outlives_the_counts(self):
        """Revenue is the expensive panel and the slowest to change."""
        from sbomify.apps.ops.services import overview

        assert revenue.CACHE_TTL_SECONDS > overview.COUNTS_CACHE_TTL_SECONDS
        assert growth.CACHE_TTL_SECONDS >= overview.COUNTS_CACHE_TTL_SECONDS
