"""Dramatiq tasks for teams/workspace operations."""

import dramatiq
from django.utils import timezone
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from sbomify.logging import getLogger

from .models import CustomDomain
from .utils import verify_custom_domain_dns

logger = getLogger(__name__)


@dramatiq.actor(queue_name="teams", max_retries=3, time_limit=60000)
@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
)
def verify_custom_domain_task(custom_domain_id: str) -> dict:
    """Verify a custom domain's DNS configuration asynchronously.

    This task performs DNS resolution to check if the domain points to the edge server IPs.

    Args:
        custom_domain_id: ID of the CustomDomain to verify

    Returns:
        Dictionary with task results including success status
    """
    try:
        logger.info(f"[TASK_verify_custom_domain] Starting verification for domain ID {custom_domain_id}")

        # Get the custom domain
        try:
            custom_domain = CustomDomain.objects.select_related("team").get(id=custom_domain_id)
        except CustomDomain.DoesNotExist:
            error_msg = f"[TASK_verify_custom_domain] Custom domain {custom_domain_id} not found"
            logger.error(error_msg)
            return {
                "custom_domain_id": custom_domain_id,
                "success": False,
                "error": "Custom domain not found",
                "timestamp": timezone.now().isoformat(),
            }

        hostname = custom_domain.hostname
        logger.info(f"[TASK_verify_custom_domain] Verifying DNS for {hostname}")

        # Perform DNS verification
        verification_result = verify_custom_domain_dns(hostname)

        if verification_result:
            # Update the domain as verified
            custom_domain.is_verified = True
            custom_domain.verified_at = timezone.now()
            custom_domain.save(update_fields=["is_verified", "verified_at", "updated_at"])

            logger.info(
                f"[TASK_verify_custom_domain] Successfully verified {hostname} for workspace {custom_domain.team.name}"
            )

            return {
                "custom_domain_id": custom_domain_id,
                "hostname": hostname,
                "team_key": custom_domain.team.key,
                "success": True,
                "verified": True,
                "verified_at": custom_domain.verified_at.isoformat(),
                "timestamp": timezone.now().isoformat(),
            }
        else:
            logger.warning(
                f"[TASK_verify_custom_domain] DNS verification failed for {hostname} "
                f"(workspace: {custom_domain.team.name})"
            )

            return {
                "custom_domain_id": custom_domain_id,
                "hostname": hostname,
                "team_key": custom_domain.team.key,
                "success": True,
                "verified": False,
                "error": "DNS verification failed",
                "timestamp": timezone.now().isoformat(),
            }

    except Exception as e:
        error_msg = f"[TASK_verify_custom_domain] Error verifying domain {custom_domain_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise  # Re-raise for retry mechanism
