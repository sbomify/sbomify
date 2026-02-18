"""
Shared utility functions for the billing module.

Consolidates helpers, utilities, and shared constants used across billing views, APIs, and processing.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Callable

from django.core.cache import cache
from django.utils import timezone

from sbomify.apps.teams.models import Member
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team


logger = getLogger(__name__)

# Shared rate-limit defaults (used by views.py and apis.py)
RATE_LIMIT = 5
RATE_LIMIT_PERIOD = 60


def require_team_owner(team: Team, user: Any) -> tuple[bool, str]:
    """Check if user is an owner of the team.

    Returns:
        (True, "") if user is owner, (False, error_message) otherwise.
    """
    is_owner = team.members.filter(member__user=user, member__role="owner").exists()
    if not is_owner:
        return False, "Only workspace owners can change billing plans"
    return True, ""


def generate_webhook_id(event: Any, obj: Any, prefix: str = "sub") -> str:
    """Generate a deterministic webhook ID for idempotency.

    Uses event.id when available, falls back to obj ID + updated timestamp.
    When 'updated' is missing, includes the current epoch second to avoid
    static keys that silently drop subsequent legitimate webhooks.
    """
    if event:
        event_id = getattr(event, "id", None)
        if event_id:
            return event_id

    obj_id = getattr(obj, "id", None) or (obj.get("id") if isinstance(obj, dict) else None)
    obj_updated = getattr(obj, "updated", None) or (obj.get("updated") if isinstance(obj, dict) else None)

    if obj_id and obj_updated:
        return f"{prefix}_{obj_id}_{obj_updated}"
    elif obj_id:
        epoch_us = int(timezone.now().timestamp() * 1_000_000)
        logger.warning("No 'updated' field on %s %s; using epoch-based webhook_id", prefix, obj_id)
        return f"{prefix}_{obj_id}_{epoch_us}"

    obj_repr = repr(obj)[:100] if obj else "none"
    deterministic_hash = hashlib.sha256(f"{prefix}_{obj_repr}".encode()).hexdigest()[:12]
    logger.critical("Unable to determine object ID for webhook_id; using repr-based hash")
    return f"{prefix}_noid_{deterministic_hash}"


def notify_team_owners(team: Team, notification_fn: Callable, *args: Any, **kwargs: Any) -> None:
    """Send a notification to all team owners.

    Args:
        team: Team instance
        notification_fn: Callable(team, member, *args, **kwargs)
    """
    team_owners = Member.objects.filter(team=team, role="owner")
    for member in team_owners:
        notification_fn(team, member, *args, **kwargs)


def check_rate_limit(key: str, limit: int = 5, period: int = 60) -> bool:
    """Check if rate limit is exceeded. Uses atomic cache operations.

    Returns True if rate limit exceeded, False otherwise.

    Fails closed: if the cache is unavailable after retries, returns True
    (rate-limited) to protect billing endpoints from abuse.
    """
    cache_key = f"ratelimit:{key}"
    count: int | None = None
    for _attempt in range(2):
        try:
            cache.add(cache_key, 0, period)
            count = cache.incr(cache_key)
            break
        except ValueError:
            cache.set(cache_key, 0, period)
    if count is None:
        logger.warning("Rate limit cache unavailable for %s — failing closed", cache_key)
        return True
    return count > limit


def handle_community_downgrade_visibility(team: Team) -> None:
    """Set all components to PUBLIC when downgrading to community plan.

    Logs an audit trail of the visibility change for traceability.
    """
    from sbomify.apps.sboms.models import Component

    affected = Component.objects.filter(team=team).exclude(visibility=Component.Visibility.PUBLIC).count()
    if affected > 0:
        Component.objects.filter(team=team).update(visibility=Component.Visibility.PUBLIC)
        logger.warning(
            "Community downgrade: set %d component(s) to PUBLIC for team %s",
            affected,
            team.key,
        )


def get_community_plan_limits() -> dict:
    """Return the standard limits dict for community plan.

    Callers should merge this with their existing billing_plan_limits
    inside their own transaction context.
    """
    from .models import BillingPlan

    try:
        plan = BillingPlan.objects.get(key=BillingPlan.KEY_COMMUNITY)
        return {
            "max_products": plan.max_products,
            "max_projects": plan.max_projects,
            "max_components": plan.max_components,
        }
    except BillingPlan.DoesNotExist:
        logger.critical("Community BillingPlan missing — returning unlimited limits")
        return {
            "max_products": None,
            "max_projects": None,
            "max_components": None,
        }


CHECKOUT_LOCK_TTL = 300  # 5 minutes


def acquire_checkout_lock(team_key: str) -> bool:
    """Acquire a cache-based lock to prevent concurrent checkout sessions for a team.

    Returns True if lock acquired, False if another checkout is already in progress.
    """
    return cache.add(f"checkout_lock:{team_key}", 1, CHECKOUT_LOCK_TTL)


def release_checkout_lock(team_key: str) -> None:
    """Release the checkout session lock for a team."""
    cache.delete(f"checkout_lock:{team_key}")


# ---------------------------------------------------------------------------
# Parsing / formatting utilities (merged from billing_utils.py)
# ---------------------------------------------------------------------------


def parse_cancel_at(cancel_at: Any) -> int | None:
    """Parse cancel_at from a Stripe subscription into an int timestamp or None.

    Handles int, float, string, and non-convertible types gracefully.
    """
    if cancel_at is None:
        return None

    if isinstance(cancel_at, (int, float)):
        return int(cancel_at) if cancel_at > 0 else None

    try:
        value = int(cancel_at)
        return value if value > 0 else None
    except (TypeError, ValueError, AttributeError):
        return None


def mask_email(email: str) -> str:
    """Mask an email address for safe logging. e.g. 'john@example.com' -> 'j***@example.com'."""
    if not email:
        return "***"
    local, sep, domain = email.partition("@")
    if not local or not sep or not domain:
        return "***"
    if len(local) <= 1:
        return f"****@{domain}"
    return f"{local[0]}***@{domain}"
