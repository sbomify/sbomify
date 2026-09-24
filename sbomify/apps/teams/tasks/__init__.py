import json
import logging
from datetime import timedelta
from typing import cast

import dramatiq
import requests
import urllib3
from django.db.models import DateTimeField, F
from django.db.models.functions import Coalesce, Greatest, Now
from django.utils import timezone

from sbomify.apps.teams.models import Team
from sbomify.apps.teams.utils import custom_domain_challenge, invalidate_custom_domain_cache
from sbomify.task_utils import record_task_breadcrumb

logger = logging.getLogger(__name__)

# Base delay in minutes
BASE_DELAY_MINUTES = 5
# Max retries cap for backoff calculation
# Note: This doesn't stop verification attempts, it just caps the backoff delay at ~3.5 days
# The system will continue checking indefinitely at this maximum interval
MAX_RETRIES = 10
# Our domain-check answer is a few hundred bytes, and whoever runs the domain
# chooses what answers the probe. A longer answer is not ours.
PROBE_MAX_BYTES = 4096


def _serves_challenge(team_id: int, domain: str) -> bool:
    """Whether the domain, fetched through public DNS, answers with its challenge."""
    url = f"https://{domain}/.well-known/com.sbomify.domain-check"
    headers = {"User-Agent": "sbomify-domain-verification/1.0"}
    try:
        # No redirects: the answer has to come from the domain itself. No retries:
        # the task's backoff schedules the next attempt.
        with requests.get(
            url, headers=headers, timeout=10, verify=True, allow_redirects=False, stream=True
        ) as response:
            logger.debug(f"Probe response status: {response.status_code}")
            if response.status_code != 200:
                return False
            body = response.raw.read(PROBE_MAX_BYTES + 1, decode_content=True)
        if len(body) > PROBE_MAX_BYTES:
            return False
        answer = json.loads(body)
    except (requests.RequestException, urllib3.exceptions.HTTPError, ValueError):
        return False
    served = answer.get("challenge") if isinstance(answer, dict) else None
    return isinstance(served, str) and served == custom_domain_challenge(team_id, domain)


@dramatiq.actor(queue_name="domain_verification", max_retries=0, time_limit=60000)
def probe_custom_domain(team_id: int, domain: str) -> None:
    """Validate one domain if it answers with its challenge.

    One message per domain, so a domain that answers slowly spends its own time
    limit instead of holding up the domains queued after it.
    """
    if not _serves_challenge(team_id, domain):
        return

    # Conditional on the domain the probe fetched: the workspace may have
    # changed it while the request was in flight.
    validated = Team.objects.filter(pk=team_id, custom_domain=domain, custom_domain_validated=False).update(
        custom_domain_validated=True,
        # Validation is what makes the custom domain the preferred one,
        # so it rewrites every absolute URL in the CSAF distribution.
        # This bypasses the model signal, so it bumps the marker itself.
        csaf_feed_updated_at=Greatest(
            Coalesce(F("csaf_feed_updated_at"), Now(), output_field=DateTimeField()),
            Now(),
            output_field=DateTimeField(),
        ),
        custom_domain_verification_failures=0,
        custom_domain_last_checked_at=timezone.now(),
    )
    if validated:
        invalidate_custom_domain_cache(domain)
        logger.info(f"Successfully validated domain {domain}")


@dramatiq.actor(time_limit=900000)  # 15 minutes
def verify_custom_domains() -> None:
    """
    Periodic task to verify unvalidated custom domains.

    This task iterates through unvalidated domains and queues a probe for each one due.
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
            # Counted before the probe runs, so a probe that times out still backs off.
            # Only if the domain is still the one read above and still pending.
            # Use F() expression for atomic increment to prevent race conditions
            counted = Team.objects.filter(
                pk=team.pk, custom_domain=team.custom_domain, custom_domain_validated=False
            ).update(
                custom_domain_verification_failures=F("custom_domain_verification_failures") + 1,
                custom_domain_last_checked_at=now,
            )
            if counted:
                probe_custom_domain.send(team.pk, cast(str, team.custom_domain))

        except Exception as e:
            logger.error(f"Error verifying domain {team.custom_domain}: {e}")


# Import cron module at end of file to ensure cron tasks are registered when this module is autodiscovered
# This must be at the end to avoid circular import (cron imports verify_custom_domains from this module)
from .. import cron as _cron  # noqa: F401, E402
