import os
from importlib.metadata import PackageNotFoundError, version

from sbomify.logging import getLogger

logger = getLogger(__name__)


def version_context(request):
    """Add version and build information to template context.

    Provides the following context variables:
    - app_version: The semantic version from package metadata
    - git_commit: Short git commit hash (7 characters)
    - git_commit_full: Full git commit SHA
    - git_ref: Git ref name (tag or branch)
    - build_type: 'release' for tag builds, 'branch' for branch builds
    - build_date: Build timestamp in RFC 3339 format
    """
    try:
        app_version = version("sbomify")
    except PackageNotFoundError:
        app_version = None  # Don't show version if package not found

    # Get build metadata from environment variables (set during Docker build)
    git_commit_short = os.environ.get("SBOMIFY_GIT_COMMIT_SHORT", "")
    git_commit_full = os.environ.get("SBOMIFY_GIT_COMMIT", "")
    git_ref = os.environ.get("SBOMIFY_GIT_REF", "")
    build_type = os.environ.get("SBOMIFY_BUILD_TYPE", "")
    build_date = os.environ.get("SBOMIFY_BUILD_DATE", "")

    return {
        "app_version": app_version,
        "git_commit": git_commit_short if git_commit_short else None,
        "git_commit_full": git_commit_full if git_commit_full else None,
        "git_ref": git_ref if git_ref else None,
        "build_type": build_type if build_type else None,
        "build_date": build_date if build_date else None,
    }


def pending_invitations_context(request):
    """Add pending invitations count to template context."""
    if not request.user.is_authenticated:
        return {}

    from django.conf import settings
    from django.core.cache import cache
    from django.utils import timezone

    from sbomify.apps.core.utils import sanitize_email_for_cache_key
    from sbomify.apps.teams.models import Invitation

    email = request.user.email or ""
    sanitized_email = sanitize_email_for_cache_key(email, user_id=getattr(getattr(request, "user", None), "id", None))
    if not sanitized_email:
        return {
            "pending_invitations_count": 0,
            "has_pending_invitations": False,
        }
    cache_key = f"pending_invitations:{sanitized_email}"
    cached = cache.get(cache_key)
    if cached is not None:
        count = cached
    else:
        count = Invitation.objects.filter(email__iexact=email, expires_at__gt=timezone.now()).count()
        ttl = getattr(settings, "PENDING_INVITATIONS_CACHE_TTL", 60)
        cache.set(cache_key, count, ttl)

    return {
        "pending_invitations_count": count,
        "has_pending_invitations": count > 0,  # Boolean for cache key to avoid key explosion
    }


def global_modals_context(request):
    """Add global modals forms to template context."""
    if not request.user.is_authenticated:
        return {}

    from sbomify.apps.teams.forms import AddTeamForm

    return {
        "add_workspace_form": AddTeamForm(),
    }


def team_context(request):
    """
    Add current team and user role to context.

    This enables global access to 'team' and 'is_owner' for banners/navigation
    without requiring every view to pass them explicitly.

    Also syncs subscription data from Stripe to ensure billing status is always up-to-date.
    """
    if not request.user.is_authenticated:
        return {}

    current_team_data = request.session.get("current_team", {})
    team_key = current_team_data.get("key")

    if not team_key:
        return {}

    try:
        from sbomify.apps.teams.models import Member, Team

        # We could use select_related hooks or simple caching here if performance is an issue
        team = Team.objects.get(key=team_key)

        # Sync subscription data from Stripe if subscription exists
        # This ensures billing status is always current for banners/notifications
        billing_limits = team.billing_plan_limits or {}
        stripe_sub_id = billing_limits.get("stripe_subscription_id")
        if stripe_sub_id:
            try:
                from sbomify.apps.billing.stripe_sync import sync_subscription_from_stripe

                # Sync in background (non-blocking) - if it fails, we still show the page
                # Use force_refresh=False to use cache, but sync will still check for changes
                result = sync_subscription_from_stripe(team, force_refresh=False)
                if result:
                    # Refresh team to get updated billing_plan_limits
                    team.refresh_from_db()
                    logger.debug(f"Successfully synced subscription for team {team_key}")
                else:
                    logger.debug(f"Sync returned False for team {team_key} (may not have subscription)")
            except Exception as e:
                # Log error but don't break page rendering if sync fails
                logger.warning(f"Failed to sync subscription for team {team_key}: {e}", exc_info=True)

        # Determine if owner
        # Optimization: Check if the session already has reliable role info,
        # but fetching DB ensures latest status (important for billing updates etc)
        is_owner = False
        member = Member.objects.filter(team=team, user=request.user).first()
        if member and member.role == "owner":
            is_owner = True

        from django.conf import settings

        return {
            "team": team,
            "is_owner": is_owner,
            "grace_period_days": getattr(settings, "PAYMENT_GRACE_PERIOD_DAYS", 3),
        }
    except Exception:
        # Fail silently to avoid crashing unrelated pages if session is stale
        return {}
