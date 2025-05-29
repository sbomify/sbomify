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


from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.utils import DatabaseError, OperationalError  # noqa: E402

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


@dramatiq.actor(queue_name="sbom_license_processing", max_retries=3, time_limit=300000, store_results=True)
@retry(
    retry=retry_if_exception_type((OperationalError, ConnectionError)),
    wait=wait_exponential(multiplier=1, min=1, max=5),  # Start with 1s, max 5s between retries
    stop=stop_after_delay(30),  # Stop after 30s total
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def process_sbom_licenses(sbom_id: str) -> Dict[str, Any]:
    """
    Process and analyze license data from an SBOM asynchronously.
    This now also extracts and populates the packages_licenses field from the SBOM file or data.
    """
    logger.info(f"[TASK_process_sbom_licenses] Received task for SBOM ID: {sbom_id}")
    try:
        with transaction.atomic():
            # Ensure database connection is alive
            connection.ensure_connection()

            logger.info(f"[TASK_process_sbom_licenses] Attempting to fetch SBOM ID: {sbom_id} from database.")
            sbom = SBOM.objects.select_for_update().get(id=sbom_id)
            logger.info(
                (
                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} fetched. "
                    f"Format: {sbom.format}, Filename: {sbom.sbom_filename}"
                )
            )

            # The incorrect license processing logic, including SBOM data loading, has been removed.
            # The SBOM model fields `licenses` and `packages_licenses` have also been removed.
            # Future implementation will handle license expressions correctly and store them appropriately.
            logger.info(
                f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Current license extraction and "
                f"analysis logic has been removed. Associated model fields are also removed."
            )

            # The SBOM is saved.
            sbom.save()  # Ensures consistency if other parts of the transaction expect a save.
            logger.debug(
                (
                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - "
                    f"Saved SBOM. License-related model fields have been removed."
                )
            )

            return {
                "sbom_id": sbom_id,
                "status": "License processing temporarily bypassed. Model fields removed.",
                "message": (
                    "Incorrect license logic and associated model fields (licenses, packages_licenses) removed. "
                    "Awaiting updated implementation for license expressions."
                ),
            }

    except SBOM.DoesNotExist:
        logger.error(f"[TASK_process_sbom_licenses] SBOM with ID {sbom_id} not found.")
        return {"error": f"SBOM with ID {sbom_id} not found"}
    except (DatabaseError, OperationalError) as db_err:
        logger.error(
            f"[TASK_process_sbom_licenses] Database error occurred processing SBOM ID {sbom_id}: {db_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except ConnectionError as conn_err:
        logger.error(
            f"[TASK_process_sbom_licenses] Connection error occurred processing SBOM ID {sbom_id}: {conn_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except Exception as e:
        logger.error(
            f"[TASK_process_sbom_licenses] An unexpected error occurred processing SBOM ID {sbom_id}: {e}",
            exc_info=True,
        )
        raise  # Re-raise to allow Dramatiq to handle retries


# Example task for testing
@dramatiq.actor
def example_task(message: str):
    logger.info(f"Processing message: {message}")
