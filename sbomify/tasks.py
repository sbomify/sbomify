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
from django.utils import timezone  # noqa: E402

from sboms.models import SBOM  # noqa: E402
from core.object_store import S3Client  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import json  # noqa: E402

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


@dramatiq.actor(queue_name="sbom_vulnerability_scanning", max_retries=3, time_limit=300000, store_results=True)
@retry(
    retry=retry_if_exception_type((OperationalError, ConnectionError, subprocess.CalledProcessError)),
    wait=wait_exponential(multiplier=1, min=1, max=10),  # Start with 1s, max 10s
    stop=stop_after_delay(60),  # Stop after 60s total
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def scan_sbom_for_vulnerabilities(sbom_id: str) -> Dict[str, Any]:
    """
    Downloads an SBOM from S3, scans it with osv-scanner, and stores the results in Redis.
    """
    logger.info(f"[TASK_scan_sbom_for_vulnerabilities] Received task for SBOM ID: {sbom_id}")
    sbom_instance = None
    temp_sbom_file = None

    try:
        # 1. Fetch SBOM metadata
        with transaction.atomic():
            connection.ensure_connection()
            logger.info(f"[TASK_scan_sbom_for_vulnerabilities] Attempting to fetch SBOM ID: {sbom_id} from database.")
            sbom_instance = SBOM.objects.get(id=sbom_id)
            logger.info(
                f"[TASK_scan_sbom_for_vulnerabilities] SBOM ID: {sbom_id} fetched. Filename: {sbom_instance.sbom_filename}"
            )

        if not sbom_instance.sbom_filename:
            logger.error(f"[TASK_scan_sbom_for_vulnerabilities] SBOM ID: {sbom_id} has no sbom_filename.")
            return {"error": f"SBOM ID: {sbom_id} has no sbom_filename."}

        # 2. Download SBOM from S3
        logger.info(f"[TASK_scan_sbom_for_vulnerabilities] Downloading SBOM {sbom_instance.sbom_filename} from S3.")
        s3_client = S3Client(bucket_type="SBOMS")
        sbom_data_bytes = s3_client.get_sbom_data(sbom_instance.sbom_filename)

        if not sbom_data_bytes:
            logger.error(
                f"[TASK_scan_sbom_for_vulnerabilities] Failed to download SBOM {sbom_instance.sbom_filename} from S3 (empty data)."
            )
            return {"error": f"Failed to download SBOM {sbom_instance.sbom_filename} from S3 (empty data)."}

        logger.info(
            f"[TASK_scan_sbom_for_vulnerabilities] Downloaded {len(sbom_data_bytes)} bytes for {sbom_instance.sbom_filename}."
        )

        # Attempt to parse as JSON to check basic integrity
        try:
            json.loads(sbom_data_bytes.decode("utf-8"))  # Try decoding as utf-8 common for json
            logger.info(
                f"[TASK_scan_sbom_for_vulnerabilities] SBOM {sbom_instance.sbom_filename} successfully parsed as JSON."
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(
                f"[TASK_scan_sbom_for_vulnerabilities] SBOM {sbom_instance.sbom_filename} is not valid JSON or has encoding issues. Error: {e}. "
                f"First 200 chars: {sbom_data_bytes[:200]}"
            )
            return {
                "error": f"SBOM {sbom_instance.sbom_filename} content is not valid JSON or has encoding issues.",
                "details": str(e),
            }

        # Determine suffix based on SBOM format
        file_suffix = ".json"  # Default
        if sbom_instance.format and "cyclonedx" in sbom_instance.format.lower():
            file_suffix = ".cyclonedx.json"
        elif sbom_instance.format and "spdx" in sbom_instance.format.lower():
            file_suffix = ".spdx.json"

        # Create a temporary file to store SBOM data
        # The tempfile needs to be writeable in binary mode for bytes, and needs to persist after closing for subprocess.
        with tempfile.NamedTemporaryFile(delete=False, mode="wb", suffix=file_suffix) as temp_file:
            temp_sbom_file = temp_file.name
            temp_file.write(sbom_data_bytes)
        logger.info(
            f"[TASK_scan_sbom_for_vulnerabilities] SBOM data written to temporary file: {temp_sbom_file} with format {sbom_instance.format}"
        )

        # 3. Execute osv-scanner
        osv_scanner_path = "/usr/local/bin/osv-scanner"  # As defined in Dockerfile
        scan_command = [osv_scanner_path, "--sbom", temp_sbom_file, "--format", "json"]
        logger.info(f"[TASK_scan_sbom_for_vulnerabilities] Executing osv-scanner: {' '.join(scan_command)}")

        process = subprocess.run(scan_command, capture_output=True, text=True, check=True)
        scan_output_json_str = process.stdout
        logger.info(f"[TASK_scan_sbom_for_vulnerabilities] osv-scanner completed successfully for SBOM ID: {sbom_id}.")
        if process.stderr:
            logger.warning(
                f"[TASK_scan_sbom_for_vulnerabilities] osv-scanner stderr for SBOM ID {sbom_id}: {process.stderr}"
            )

        # 4. Store results in Redis
        # Ensure redis_broker is available and get a client
        if dramatiq.get_broker() and hasattr(dramatiq.get_broker(), "client"):
            redis_client = dramatiq.get_broker().client
            timestamp = timezone.now().isoformat()
            redis_key = f"osv_scan_result:{sbom_id}:{timestamp}"
            # Store the raw JSON string. Parsing can be done by the consumer.
            redis_client.set(redis_key, scan_output_json_str, ex=settings.REDIS_RESULT_EXPIRY_SECONDS)  # Use an expiry
            logger.info(
                f"[TASK_scan_sbom_for_vulnerabilities] Scan results for SBOM ID {sbom_id} stored in Redis with key: {redis_key}"
            )
            result_message = f"Scan successful, results stored in Redis: {redis_key}"
        else:
            logger.error(
                "[TASK_scan_sbom_for_vulnerabilities] Redis client not available from Dramatiq broker. Cannot store results."
            )
            result_message = "Scan successful, but Redis client not available to store results."

        return {
            "sbom_id": sbom_id,
            "status": "Scan completed.",
            "message": result_message,
            "scan_output_preview": json.loads(scan_output_json_str)[:1]
            if scan_output_json_str
            else None,  # Preview of first result item
        }

    except SBOM.DoesNotExist:
        logger.error(f"[TASK_scan_sbom_for_vulnerabilities] SBOM with ID {sbom_id} not found.")
        return {"error": f"SBOM with ID {sbom_id} not found"}
    except subprocess.CalledProcessError as e:
        logger.error(
            f"[TASK_scan_sbom_for_vulnerabilities] osv-scanner failed for SBOM ID {sbom_id}. "
            f"Return code: {e.returncode}. Output: {e.output}. Stderr: {e.stderr}",
            exc_info=True,
        )
        # Include scanner output in the error if possible
        error_detail = {
            "error": "osv-scanner execution failed.",
            "return_code": e.returncode,
            "stdout": e.stdout,
            "stderr": e.stderr,
        }
        if sbom_instance:  # Add sbom_filename if available
            error_detail["sbom_filename"] = sbom_instance.sbom_filename
        # Do not re-raise here if tenacity should not retry subprocess errors,
        # or re-raise if retries are desired for transient scanner issues.
        # For now, returning error to prevent retry loops on persistent scan failures.
        return error_detail
    except (DatabaseError, OperationalError) as db_err:
        logger.error(
            f"[TASK_scan_sbom_for_vulnerabilities] Database error occurred processing SBOM ID {sbom_id}: {db_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except ConnectionError as conn_err:  # General connection error
        logger.error(
            f"[TASK_scan_sbom_for_vulnerabilities] Connection error occurred processing SBOM ID {sbom_id}: {conn_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except Exception as e:
        logger.error(
            f"[TASK_scan_sbom_for_vulnerabilities] An unexpected error occurred processing SBOM ID {sbom_id}: {e}",
            exc_info=True,
        )
        # For unexpected errors, it's often better to let Dramatiq handle retries if configured.
        raise
    finally:
        # 5. Cleanup temporary file
        if temp_sbom_file and os.path.exists(temp_sbom_file):
            try:
                os.remove(temp_sbom_file)
                logger.info(f"[TASK_scan_sbom_for_vulnerabilities] Cleaned up temporary file: {temp_sbom_file}")
            except OSError as e:
                logger.error(
                    f"[TASK_scan_sbom_for_vulnerabilities] Error deleting temporary file {temp_sbom_file}: {e}"
                )


# Example task for testing
@dramatiq.actor
def example_task(message: str):
    logger.info(f"Processing message: {message}")
