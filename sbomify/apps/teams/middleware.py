import logging
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from sbomify.apps.teams.models import Team

logger = logging.getLogger(__name__)


class CustomDomainMiddleware(MiddlewareMixin):
    """
    Middleware to handle requests to custom domains.

    This middleware:
    1. Checks if the Host header is allowed (either a system host or a valid custom domain).
    2. If it's a valid custom domain that hasn't been validated yet, marks it as validated.
    """

    def process_request(self, request):
        # Get host directly from META to avoid Django's ALLOWED_HOSTS check
        # which happens in request.get_host()
        host = request.META.get("HTTP_HOST", "").split(":")[0].lower()

        if not host:
            return None

        # 1. Check system hosts first (fast path)
        # We need to parse APP_BASE_URL to get the system hostname
        if hasattr(settings, "APP_BASE_URL"):
            system_host = urlparse(settings.APP_BASE_URL).netloc.split(":")[0].lower()
            if host == system_host:
                return None

        if host in ["localhost", "127.0.0.1", "testserver", "sbomify-backend"]:
            return None

        # 2. Check custom domains in database
        try:
            team = Team.objects.filter(custom_domain=host).first()
            if team:
                # Found a valid custom domain!

                # Auto-validate if not already validated
                if not team.custom_domain_validated:
                    from sbomify.apps.teams.utils import invalidate_custom_domain_cache

                    logger.info(f"Validating custom domain {host} for team {team.key} based on incoming traffic")
                    team.custom_domain_validated = True
                    team.custom_domain_verification_failures = 0
                    team.custom_domain_last_checked_at = timezone.now()
                    team.save(
                        update_fields=[
                            "custom_domain_validated",
                            "custom_domain_verification_failures",
                            "custom_domain_last_checked_at",
                        ]
                    )

                    # Invalidate cache so future requests see validated status
                    invalidate_custom_domain_cache(host)

                # Allow request to proceed
                return None
        except Exception as e:
            logger.error(f"Error checking custom domain for host {host}: {e}")

        # If we got here, the host is not allowed
        # Note: If ALLOWED_HOSTS is set to dynamic class in settings, Django's CommonMiddleware
        # or core handler might have already checked it, but this adds an extra layer of
        # security and handles the validation logic.
        # However, since we're using a dynamic ALLOWED_HOSTS list wrapper in settings.py,
        # Django's built-in host validation will query the DB.
        # This middleware is primarily for the *side effect* of validation.

        return None
