import logging
from datetime import timedelta

import dramatiq
import requests
from django.utils import timezone

from sbomify.apps.teams.models import Team

logger = logging.getLogger(__name__)

# Base delay in minutes
BASE_DELAY_MINUTES = 5
# Max retries before giving up (or checking very infrequently)
MAX_RETRIES = 10


@dramatiq.actor(time_limit=300000)  # 5 minutes
def verify_custom_domains():
    """
    Periodic task to verify unvalidated custom domains.

    This task iterates through unvalidated domains and sends a probe request.
    It uses exponential backoff to avoid spamming domains that are not yet configured.
    """
    now = timezone.now()

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
            # failures=10 -> ~3.5 days
            failures = min(team.custom_domain_verification_failures, MAX_RETRIES)
            backoff_minutes = BASE_DELAY_MINUTES * (2**failures)
            next_check_time = team.custom_domain_last_checked_at + timedelta(minutes=backoff_minutes)

            if now < next_check_time:
                continue

        logger.info(f"Probing custom domain {team.custom_domain} for team {team.key}")

        try:
            # Send a probe request
            # We use a short timeout because we just want to see if it reaches us
            # We expect the request to hit our middleware, which will validate the domain
            # even if this request eventually returns 404 or something else.
            # However, for the middleware to trigger, the DNS must point to us.

            # We add a special header so we can potentially identify these probes if needed
            headers = {"User-Agent": "sbomify-domain-verification/1.0"}

            # Try HTTPS first, then HTTP
            protocol = "https"
            url = f"{protocol}://{team.custom_domain}/health"

            try:
                _ = requests.get(url, headers=headers, timeout=10, verify=True)
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

            # If we are here, validation failed (middleware didn't trigger or request failed)
            team.custom_domain_verification_failures += 1
            team.custom_domain_last_checked_at = now
            team.save(update_fields=["custom_domain_verification_failures", "custom_domain_last_checked_at"])

        except Exception as e:
            logger.error(f"Error verifying domain {team.custom_domain}: {e}")
