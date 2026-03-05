"""TEA API response caching utilities.

Provides namespaced cache keys, a ``@tea_cached`` decorator for Django Ninja
endpoints, and workspace-wide invalidation via django-redis's delete_pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

from sbomify.logging import getLogger

log = getLogger(__name__)

TEA_CACHE_PREFIX = "tea"

# Attribute name used to pass the resolved Team from the decorator to the endpoint.
# Set on HttpRequest by @tea_cached; read by endpoints as ``request.tea_team``.
TEA_TEAM_ATTR = "tea_team"


def tea_cache_key(team_key: str, *parts: str) -> str:
    """Build a namespaced TEA cache key."""
    return f"{TEA_CACHE_PREFIX}:{team_key}:{':'.join(parts)}"


def get_tea_cache(key: str) -> Any | None:
    """Get from cache. Returns None if TTL is 0 (disabled) or cache miss."""
    if not settings.TEA_CACHE_TTL:
        return None
    try:
        return cache.get(key)
    except Exception:
        log.exception("Failed to read TEA cache key %s", key)
        return None


def set_tea_cache(key: str, value: Any) -> None:
    """Set cache with configured TTL. No-op if TTL is 0."""
    ttl = settings.TEA_CACHE_TTL
    if ttl:
        try:
            cache.set(key, value, ttl)
        except Exception:
            log.exception("Failed to write TEA cache key %s", key)


def invalidate_tea_cache(team_key: str) -> None:
    """Delete all TEA cache entries for a workspace."""
    pattern = f"{TEA_CACHE_PREFIX}:{team_key}:*"
    if hasattr(cache, "delete_pattern"):
        cache.delete_pattern(pattern)
        log.debug("Invalidated TEA cache for workspace %s", team_key)
    else:
        log.debug(
            "Skipped TEA cache invalidation for workspace %s (backend %s has no delete_pattern)",
            team_key,
            type(cache).__name__,
        )


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def tea_cached(key_builder: Callable[..., tuple[str, ...]]) -> Callable[..., Any]:
    """Caching decorator for TEA API endpoints.

    Handles workspace resolution and response caching so that endpoints
    contain only business logic.

    ``key_builder`` receives the **same keyword arguments** as the endpoint
    (excluding ``request``) and must return a tuple of strings that form the
    cache key after the ``tea:{team_key}:`` prefix.

    The resolved ``Team`` instance is set on ``request.tea_team`` so the
    endpoint can access it without calling ``get_team_or_400`` itself.

    Only explicit ``(200, body)`` response tuples are cached; error responses
    pass through uncached.

    Note: This decorator relies on ``@functools.wraps`` to preserve the
    original function's signature, which Django Ninja uses for parameter
    introspection and OpenAPI schema generation.

    Usage::

        @router.get("/product/{uuid}", ...)
        @tea_cached(lambda uuid, **_: ("product", uuid))
        def get_product(request, uuid, workspace_key=None):
            team = request.tea_team
            ...
    """
    from sbomify.apps.tea.utils import get_team_or_400

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(request: HttpRequest, **kwargs: Any) -> Any:
            workspace_key = kwargs.get("workspace_key")
            team_or_error = get_team_or_400(request, workspace_key, func.__name__)
            if isinstance(team_or_error, tuple):
                return team_or_error
            team = team_or_error
            setattr(request, TEA_TEAM_ATTR, team)

            try:
                parts = key_builder(**kwargs)
            except Exception:
                log.exception("Failed to build cache key for %s with kwargs=%s", func.__name__, list(kwargs.keys()))
                return func(request, **kwargs)

            cache_key = tea_cache_key(team.key, *parts)
            cached = get_tea_cache(cache_key)
            if cached is not None:
                return cached

            response = func(request, **kwargs)

            # Only cache explicit (200, body) tuples — the Django Ninja convention.
            is_cacheable = isinstance(response, tuple) and len(response) == 2 and response[0] == 200
            if is_cacheable:
                set_tea_cache(cache_key, response)

            return response

        return wrapper

    return decorator
