import logging
from datetime import timedelta

import dramatiq
import requests
from django.utils import timezone

from sbomify.apps.teams.models import Team
from sbomify.task_utils import record_task_breadcrumb

logger = logging.getLogger(__name__)

# Base delay in minutes
BASE_DELAY_MINUTES = 5
# Max retries cap for backoff calculation
# Note: This doesn't stop verification attempts, it just caps the backoff delay at ~3.5 days
# The system will continue checking indefinitely at this maximum interval
MAX_RETRIES = 10


@dramatiq.actor(time_limit=900000)  # 15 minutes
def verify_custom_domains():
    """
    Periodic task to verify unvalidated custom domains.

    This task iterates through unvalidated domains and sends a probe request.
    It uses exponential backoff to avoid spamming domains that are not yet configured.

    Time limit: 15 minutes to accommodate large numbers of domains.
    If the number of domains grows further, implement batching/pagination.
    """
    now = timezone.now()
    record_task_breadcrumb("verify_custom_domains", "start")

    # Get unvalidated domains
    teams = Team.objects.filter(custom_domain__isnull=False, custom_domain_validated=False).exclude(custom_domain="")

    for team in teams:
        # Check if it's time to retry based on failure count
        if team.custom_domain_last_checked_at:
            # Calculate backoff: base * 2^failures
            # failures=0 -> 5 min
            # failures=1 -> 10 min
            # failures=2 -> 20 min
            # ...
            # failures=10+ -> ~3.5 days (plateaus at MAX_RETRIES)
            # Note: We never stop trying, the backoff just caps at ~3.5 days
            failures = min(team.custom_domain_verification_failures, MAX_RETRIES)
            backoff_minutes = BASE_DELAY_MINUTES * (2**failures)
            next_check_time = team.custom_domain_last_checked_at + timedelta(minutes=backoff_minutes)

            if now < next_check_time:
                continue

        logger.info(f"Probing custom domain {team.custom_domain} for team {team.key}")
        record_task_breadcrumb(
            "verify_custom_domains",
            "probe",
            data={"team_id": str(team.id), "domain": team.custom_domain},
        )

        try:
            # Send a probe request
            # We use a short timeout because we just want to see if it reaches us
            # We expect the request to hit our middleware, which will validate the domain
            # even if this request eventually returns 404 or something else.
            # However, for the middleware to trigger, the DNS must point to us.

            # We add a special header so we can potentially identify these probes if needed
            headers = {"User-Agent": "sbomify-domain-verification/1.0"}

            # Use .well-known/com.sbomify.domain-check endpoint to ensure ALLOWED_HOSTS is validated
            # This prevents random domains from using our server as a verification endpoint
            protocol = "https"
            url = f"{protocol}://{team.custom_domain}/.well-known/com.sbomify.domain-check"

            try:
                response = requests.get(url, headers=headers, timeout=10, verify=True)
                logger.debug(f"Probe response status: {response.status_code}")
                # If we get a response (even 404), it means DNS is likely configured
                # and pointing to a server. If it points to US, our middleware
                # should have intercepted it and marked it valid.

                # Check if it was validated by the middleware (refresh from DB)
                team.refresh_from_db()
                if team.custom_domain_validated:
                    logger.info(f"Successfully validated domain {team.custom_domain}")
                    continue

            except requests.RequestException:
                # HTTPS failed, try HTTP? Or just count as failure.
                # Let's count as failure for now.
                pass

            # If we are here, validation failed (endpoint didn't validate or request failed)
            # Use F() expression for atomic increment to prevent race conditions
            from django.db.models import F

            Team.objects.filter(pk=team.pk).update(
                custom_domain_verification_failures=F("custom_domain_verification_failures") + 1,
                custom_domain_last_checked_at=now,
            )

        except Exception as e:
            logger.error(f"Error verifying domain {team.custom_domain}: {e}")


# Import cron module at end of file to ensure cron tasks are registered when this module is autodiscovered
# This must be at the end to avoid circular import (cron imports verify_custom_domains from this module)
from .. import cron as _cron  # noqa: F401, E402
