"""
Dramatiq tasks for the sbomify application.

This module contains all the background tasks that are processed by Dramatiq workers.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

import dramatiq
from django.db import transaction
from django.utils import timezone as django_timezone
from dramatiq.brokers.redis import RedisBroker
from dramatiq.results import Results
from dramatiq.results.backends import RedisBackend
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_delay,
    wait_exponential,
)

# Set up Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sbomify.settings")
import django  # noqa: E402

django.setup()


import json  # noqa: E402

from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.utils import DatabaseError, OperationalError  # noqa: E402

from core.object_store import S3Client  # noqa: E402
from sboms.models import SBOM  # noqa: E402

# Configure Dramatiq
if not (getattr(settings, "TESTING", False) or os.environ.get("PYTEST_CURRENT_TEST")):
    redis_broker = RedisBroker(url=settings.REDIS_WORKER_URL)
    result_backend = RedisBackend(url=settings.REDIS_WORKER_URL)
    redis_broker.add_middleware(Results(backend=result_backend))
    dramatiq.set_broker(redis_broker)

logger = logging.getLogger(__name__)


def log_retry_attempt(retry_state):
    """Log retry attempts with detailed information."""
    logger.warning(
        f"Retrying {retry_state.fn.__name__} after {retry_state.seconds_since_start:.2f}s "
        f"(attempt {retry_state.attempt_number}) due to {retry_state.outcome.exception()}"
    )


# License processing task has been removed - functionality moved to native model fields
# License processing is now handled directly during SBOM upload via ComponentLicense model


@dramatiq.actor(queue_name="sbom_ntia_compliance", max_retries=3, time_limit=300000, store_results=True)
@retry(
    retry=retry_if_exception_type((OperationalError, ConnectionError)),
    wait=wait_exponential(multiplier=1, min=1, max=5),  # Start with 1s, max 5s between retries
    stop=stop_after_delay(30),  # Stop after 30s total
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def check_sbom_ntia_compliance(sbom_id: str) -> Dict[str, Any]:
    """
    Check SBOM for NTIA minimum elements compliance.

    Downloads the SBOM from S3, validates it against NTIA requirements,
    and stores the results in the database.
    """
    logger.info(f"[TASK_check_sbom_ntia_compliance] Starting NTIA compliance check for SBOM ID: {sbom_id}")

    try:
        with transaction.atomic():
            # Ensure database connection is alive
            connection.ensure_connection()

            logger.info(f"[TASK_check_sbom_ntia_compliance] Fetching SBOM ID: {sbom_id} from database.")
            sbom = SBOM.objects.select_for_update().get(id=sbom_id)
            logger.info(
                f"[TASK_check_sbom_ntia_compliance] SBOM ID: {sbom_id} fetched. "
                f"Format: {sbom.format}, Filename: {sbom.sbom_filename}"
            )

            if not sbom.sbom_filename:
                logger.error(f"[TASK_check_sbom_ntia_compliance] SBOM ID: {sbom_id} has no sbom_filename.")
                return {"error": f"SBOM ID: {sbom_id} has no sbom_filename."}

            # Download SBOM from S3
            logger.debug(f"[TASK_check_sbom_ntia_compliance] Downloading SBOM {sbom.sbom_filename} from S3.")
            s3_client = S3Client(bucket_type="SBOMS")
            sbom_data_bytes = s3_client.get_sbom_data(sbom.sbom_filename)

            if not sbom_data_bytes:
                logger.error(
                    f"[TASK_check_sbom_ntia_compliance] Failed to download SBOM "
                    f"{sbom.sbom_filename} from S3 (empty data)."
                )
                return {"error": f"Failed to download SBOM {sbom.sbom_filename} from S3 (empty data)."}

            logger.debug(
                f"[TASK_check_sbom_ntia_compliance] Downloaded {len(sbom_data_bytes)} bytes for {sbom.sbom_filename}."
            )

            # Parse SBOM data
            try:
                sbom_data_str = sbom_data_bytes.decode("utf-8")
                sbom_data = json.loads(sbom_data_str)
                logger.debug(
                    f"[TASK_check_sbom_ntia_compliance] SBOM {sbom.sbom_filename} successfully parsed as JSON."
                )
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.error(
                    f"[TASK_check_sbom_ntia_compliance] SBOM {sbom.sbom_filename} "
                    f"is not valid JSON or has encoding issues. Error: {e}"
                )
                return {
                    "error": f"SBOM {sbom.sbom_filename} content is not valid JSON or has encoding issues.",
                    "details": str(e),
                }

            # Perform NTIA compliance validation
            from sboms.ntia_validator import validate_sbom_ntia_compliance

            logger.debug(f"[TASK_check_sbom_ntia_compliance] Running NTIA validation for SBOM {sbom_id}")
            validation_result = validate_sbom_ntia_compliance(sbom_data, sbom.format)

            # Update SBOM with validation results
            sbom.ntia_compliance_status = validation_result.status.value
            # Convert result to dict with JSON-serializable datetime
            result_dict = validation_result.dict()
            if "checked_at" in result_dict and result_dict["checked_at"]:
                result_dict["checked_at"] = result_dict["checked_at"].isoformat()
            sbom.ntia_compliance_details = result_dict
            sbom.ntia_compliance_checked_at = datetime.now(timezone.utc)
            sbom.save()

            logger.info(
                f"[TASK_check_sbom_ntia_compliance] NTIA compliance check completed for SBOM ID: {sbom_id}. "
                f"Status: {validation_result.status.value}, Errors: {validation_result.error_count}"
            )

            return {
                "sbom_id": sbom_id,
                "status": "NTIA compliance check completed",
                "compliance_status": validation_result.status.value,
                "is_compliant": validation_result.is_compliant,
                "error_count": validation_result.error_count,
                "message": "NTIA compliance check completed successfully",
            }

    except SBOM.DoesNotExist:
        logger.error(f"[TASK_check_sbom_ntia_compliance] SBOM with ID {sbom_id} not found.")
        return {"error": f"SBOM with ID {sbom_id} not found"}
    except (DatabaseError, OperationalError) as db_err:
        logger.error(
            f"[TASK_check_sbom_ntia_compliance] Database error occurred processing SBOM ID {sbom_id}: {db_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except ConnectionError as conn_err:
        logger.error(
            f"[TASK_check_sbom_ntia_compliance] Connection error occurred processing SBOM ID {sbom_id}: {conn_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except Exception as e:
        logger.error(
            f"[TASK_check_sbom_ntia_compliance] An unexpected error occurred processing SBOM ID {sbom_id}: {e}",
            exc_info=True,
        )
        raise  # Re-raise to allow Dramatiq to handle retries


@dramatiq.actor(queue_name="sbom_vulnerability_scanning", max_retries=3, time_limit=360000, store_results=True)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def scan_sbom_for_vulnerabilities_unified(sbom_id: str) -> Dict[str, Any]:
    """
    Unified vulnerability scanning task that routes to OSV or Dependency Track based on team settings.

    This replaces the original OSV-only scanning task with a provider-agnostic approach.
    """
    logger.info(f"[TASK_scan_sbom_for_vulnerabilities_unified] Starting vulnerability scan for SBOM ID: {sbom_id}")
    sbom_instance = None

    try:
        # 1. Fetch SBOM metadata
        with transaction.atomic():
            connection.ensure_connection()
            logger.debug(f"[TASK_scan_sbom_for_vulnerabilities_unified] Fetching SBOM ID: {sbom_id} from database.")
            sbom_instance = SBOM.objects.get(id=sbom_id)
            logger.debug(
                f"[TASK_scan_sbom_for_vulnerabilities_unified] SBOM ID: {sbom_id} fetched. "
                f"Filename: {sbom_instance.sbom_filename}, Team: {sbom_instance.component.team.key}"
            )

        if not sbom_instance.sbom_filename:
            logger.error(f"[TASK_scan_sbom_for_vulnerabilities_unified] SBOM ID: {sbom_id} has no sbom_filename.")
            return {"error": f"SBOM ID: {sbom_id} has no sbom_filename."}

        # 2. Download SBOM from S3
        logger.debug(
            f"[TASK_scan_sbom_for_vulnerabilities_unified] Downloading SBOM {sbom_instance.sbom_filename} from S3."
        )
        s3_client = S3Client(bucket_type="SBOMS")
        sbom_data_bytes = s3_client.get_sbom_data(sbom_instance.sbom_filename)

        if not sbom_data_bytes:
            logger.error(
                f"[TASK_scan_sbom_for_vulnerabilities_unified] Failed to download SBOM "
                f"{sbom_instance.sbom_filename} from S3 (empty data)."
            )
            return {"error": f"Failed to download SBOM {sbom_instance.sbom_filename} from S3 (empty data)."}

        logger.debug(
            f"[TASK_scan_sbom_for_vulnerabilities_unified] Downloaded {len(sbom_data_bytes)} bytes "
            f"for {sbom_instance.sbom_filename}."
        )

        # Attempt to parse as JSON to check basic integrity
        try:
            json.loads(sbom_data_bytes.decode("utf-8"))
            logger.debug(
                f"[TASK_scan_sbom_for_vulnerabilities_unified] SBOM {sbom_instance.sbom_filename} "
                f"successfully parsed as JSON."
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(
                f"[TASK_scan_sbom_for_vulnerabilities_unified] SBOM {sbom_instance.sbom_filename} "
                f"is not valid JSON or has encoding issues. Error: {e}. "
                f"First 200 chars: {sbom_data_bytes[:200]}"
            )
            return {
                "error": (f"SBOM {sbom_instance.sbom_filename} content is not valid JSON or has encoding issues."),
                "details": str(e),
            }

        # 3. Perform vulnerability scan using the unified service
        from vulnerability_scanning.services import VulnerabilityScanningService

        service = VulnerabilityScanningService()
        results = service.scan_sbom_for_vulnerabilities(sbom_instance, sbom_data_bytes, scan_trigger="upload")

        logger.info(
            f"[TASK_scan_sbom_for_vulnerabilities_unified] Completed vulnerability scan for SBOM ID: {sbom_id}. "
            f"Results: {results.get('summary', 'No summary available')}"
        )

        return results

    except SBOM.DoesNotExist:
        logger.error(f"[TASK_scan_sbom_for_vulnerabilities_unified] SBOM with ID {sbom_id} not found.")
        return {"error": f"SBOM with ID {sbom_id} not found"}
    except (DatabaseError, OperationalError) as db_err:
        logger.error(
            f"[TASK_scan_sbom_for_vulnerabilities_unified] Database error occurred "
            f"processing SBOM ID {sbom_id}: {db_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except ConnectionError as conn_err:  # General connection error
        logger.error(
            f"[TASK_scan_sbom_for_vulnerabilities_unified] Connection error occurred processing SBOM "
            f"ID {sbom_id}: {conn_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except Exception as e:
        logger.error(
            f"[TASK_scan_sbom_for_vulnerabilities_unified] An unexpected error occurred processing "
            f"SBOM ID {sbom_id}: {e}",
            exc_info=True,
        )
        # For unexpected errors, it's often better to let Dramatiq handle retries if configured.
        raise


@dramatiq.actor(queue_name="weekly_vulnerability_scan", max_retries=3, time_limit=900000, store_results=True)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_delay(300),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def weekly_vulnerability_scan_task(
    days_back: int = 7, team_key: str = None, force_rescan: bool = False, max_releases: int = None
) -> Dict[str, Any]:
    """
    Weekly vulnerability scanning task for all tagged releases.

    This task:
    1. Finds all releases with tagged SBOMs within the specified timeframe
    2. Scans each SBOM using the team's configured vulnerability provider
    3. Stores results in PostgreSQL for time series analysis
    4. Tracks scan progress and provides detailed reporting

    Args:
        days_back: Only scan releases created in the last N days (default: 7)
        team_key: Only scan releases for a specific team (for testing)
        force_rescan: Force rescan even if recent scans exist
        max_releases: Maximum number of releases to scan (for testing)

    Returns:
        Dictionary with scan statistics and results
    """
    logger.info("[TASK_weekly_vulnerability_scan] Starting weekly vulnerability scan")

    try:
        from vulnerability_scanning.services import get_weekly_scan_targets, perform_weekly_scans

        # Get scan targets
        releases = get_weekly_scan_targets(days_back, team_key, max_releases)

        if not releases:
            logger.info("[TASK_weekly_vulnerability_scan] No releases found for scanning")
            return {
                "status": "completed",
                "total_releases": 0,
                "total_sboms": 0,
                "successful_scans": 0,
                "failed_scans": 0,
                "skipped_scans": 0,
                "message": "No releases found for scanning",
            }

        # Perform scans (OSV is now available for all teams)
        scan_results = perform_weekly_scans(releases, force_rescan)

        logger.info(
            f"[TASK_weekly_vulnerability_scan] Weekly vulnerability scan completed. "
            f"Processed {scan_results['total_releases']} releases, "
            f"{scan_results['successful_scans']} successful scans"
        )

        return {"status": "completed", **scan_results, "completed_at": django_timezone.now().isoformat()}

    except Exception as e:
        logger.exception("[TASK_weekly_vulnerability_scan] Weekly vulnerability scan failed")
        return {"status": "failed", "error": str(e), "failed_at": django_timezone.now().isoformat()}


# Note: vulnerability_scanning.tasks module still exists but is not imported here
# to avoid duplicate actor registration. The main tasks are now centralized here.


# Example task for testing
@dramatiq.actor
def example_task(message: str):
    logger.info(f"Processing message: {message}")
    return {"result": f"Processed: {message}"}
