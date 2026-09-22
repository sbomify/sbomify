"""Per-panel caching.

Every panel caches under its own key with its own lifetime, rather than the
whole page sharing one entry. That is not tidiness: the panels cost wildly
different amounts and go stale at wildly different rates. Recurring revenue
walks every paying workspace and moves when a subscription changes, perhaps
daily. A row count is one query and can be a few minutes old without anybody
caring.

Sharing one entry forces the cheapest panel's staleness onto the dearest
panel's cost, and means one slow panel expiring takes the rest of the page
with it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from django.core.cache import cache

T = TypeVar("T")

KEY_PREFIX = "ops:panel"


def panel(name: str, ttl_seconds: int, build: Callable[[], T], *, refresh: bool = False) -> T:
    """Return a panel's value, building it only when its own entry is cold."""
    key = f"{KEY_PREFIX}:{name}"

    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

    value = build()
    cache.set(key, value, ttl_seconds)
    return value
