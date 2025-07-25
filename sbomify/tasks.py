"""
Dramatiq tasks for the sbomify application.

This module contains all the background tasks that are processed by Dramatiq workers.
"""

import logging
import os
from typing import Any, Dict

import dramatiq
from django.db import transaction
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


@dramatiq.actor(queue_name="sbom_processing", max_retries=3, time_limit=300000, store_results=True)
@retry(
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def process_sbom_and_create_components_task(sbom_id: str) -> Dict[str, Any]:
    """
    Process an SBOM file and create Component instances.

    This is a comprehensive task that:
    1. Downloads SBOM from S3
    2. Parses SBOM metadata
    3. Creates/updates Component instances
    4. Creates License mappings
    5. Handles packaging metadata
    6. Stores vulnerabilities from the SBOM
    7. Queues vulnerability scanning task

    Args:
        sbom_id: UUID of the SBOM to process

    Returns:
        Dictionary with processing results and statistics
    """
    logger.info(f"[TASK_process_sbom] Starting SBOM processing for ID: {sbom_id}")
    sbom_instance = None

    try:
        # 1. Fetch SBOM metadata
        with transaction.atomic():
            connection.ensure_connection()
            logger.debug(f"[TASK_process_sbom] Fetching SBOM ID: {sbom_id} from database.")
            sbom_instance = SBOM.objects.get(id=sbom_id)
            logger.debug(
                f"[TASK_process_sbom] SBOM ID: {sbom_id} fetched. "
                f"Filename: {sbom_instance.sbom_filename}, Team: {sbom_instance.component.team.key}"
            )

        if not sbom_instance.sbom_filename:
            logger.error(f"[TASK_process_sbom] SBOM ID: {sbom_id} has no sbom_filename.")
            return {"error": f"SBOM ID: {sbom_id} has no sbom_filename."}

        # 2. Download SBOM from S3
        logger.debug(f"[TASK_process_sbom] Downloading SBOM {sbom_instance.sbom_filename} from S3.")
        s3_client = S3Client(bucket_type="SBOMS")
        sbom_data_bytes = s3_client.get_sbom_data(sbom_instance.sbom_filename)

        if not sbom_data_bytes:
            logger.error(
                f"[TASK_process_sbom] Failed to download SBOM {sbom_instance.sbom_filename} from S3 (empty data)."
            )
            return {"error": f"Failed to download SBOM {sbom_instance.sbom_filename} from S3 (empty data)."}

        logger.debug(f"[TASK_process_sbom] Downloaded {len(sbom_data_bytes)} bytes for {sbom_instance.sbom_filename}.")

        # Attempt to parse as JSON to check basic integrity
        try:
            sbom_data = json.loads(sbom_data_bytes.decode("utf-8"))
            logger.debug(f"[TASK_process_sbom] SBOM {sbom_instance.sbom_filename} successfully parsed as JSON.")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(
                f"[TASK_process_sbom] SBOM {sbom_instance.sbom_filename} is not valid JSON or has encoding issues. "
                f"Error: {e}. First 200 chars: {sbom_data_bytes[:200]}"
            )
            return {
                "error": (f"SBOM {sbom_instance.sbom_filename} content is not valid JSON or has encoding issues."),
                "details": str(e),
            }

        # 3. Process SBOM using unified processor
        from sboms.utils import process_sbom_data

        results = process_sbom_data(sbom_instance, sbom_data)

        logger.info(
            f"[TASK_process_sbom] Completed SBOM processing for ID: {sbom_id}. "
            f"Created/updated {results.get('components_processed', 0)} components"
        )

        # 4. Queue vulnerability scanning task
        try:
            from vulnerability_scanning.tasks import scan_sbom_for_vulnerabilities_unified

            scan_task = scan_sbom_for_vulnerabilities_unified.send(sbom_id)
            logger.info(f"[TASK_process_sbom] Queued vulnerability scan task {scan_task.message_id} for SBOM {sbom_id}")
            results["vulnerability_scan_queued"] = scan_task.message_id
        except Exception as e:
            logger.warning(f"[TASK_process_sbom] Failed to queue vulnerability scan for SBOM {sbom_id}: {e}")
            results["vulnerability_scan_error"] = str(e)

        return results

    except SBOM.DoesNotExist:
        logger.error(f"[TASK_process_sbom] SBOM with ID {sbom_id} not found.")
        return {"error": f"SBOM with ID {sbom_id} not found"}
    except (DatabaseError, OperationalError) as db_err:
        logger.error(
            f"[TASK_process_sbom] Database error occurred processing SBOM ID {sbom_id}: {db_err}", exc_info=True
        )
        raise  # Re-raise to allow tenacity to handle retries
    except Exception as e:
        logger.error(
            f"[TASK_process_sbom] An unexpected error occurred processing SBOM ID {sbom_id}: {e}", exc_info=True
        )
        # For unexpected errors, it's often better to let Dramatiq handle retries if configured.
        raise


# Note: Vulnerability scanning tasks have been moved to vulnerability_scanning.tasks module
# to avoid duplication and provide better organization. This includes:
# - scan_sbom_for_vulnerabilities_unified
# - weekly_vulnerability_scan_task
# - periodic_dependency_track_polling_task
# - recurring_dependency_track_backfill_task


# Example task for testing
@dramatiq.actor
def example_task(message: str):
    logger.info(f"Processing message: {message}")
    return {"result": f"Processed: {message}"}
