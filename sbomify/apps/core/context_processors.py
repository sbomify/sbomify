from importlib.metadata import PackageNotFoundError, version


def version_context(request):
    """Add version information to template context."""
    try:
        app_version = version("sbomify")
    except PackageNotFoundError:
        app_version = None  # Don't show version if package not found

    return {"app_version": app_version}


def pending_invitations_context(request):
    """Add pending invitations count to template context."""
    if not request.user.is_authenticated:
        return {}

    from django.utils import timezone

    from sbomify.apps.teams.models import Invitation

    count = Invitation.objects.filter(email__iexact=request.user.email, expires_at__gt=timezone.now()).count()

    return {"pending_invitations_count": count}
