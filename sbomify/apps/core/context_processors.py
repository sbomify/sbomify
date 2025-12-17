import os
from importlib.metadata import PackageNotFoundError, version


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

    from django.utils import timezone

    from sbomify.apps.teams.models import Invitation

    count = Invitation.objects.filter(email__iexact=request.user.email, expires_at__gt=timezone.now()).count()

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
