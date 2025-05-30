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
import subprocess  # noqa: E402
import tempfile  # noqa: E402

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
    logger.info(f"[TASK_scan_sbom_for_vulnerabilities] Starting vulnerability scan for SBOM ID: {sbom_id}")
    sbom_instance = None
    temp_sbom_file = None

    try:
        # 1. Fetch SBOM metadata
        with transaction.atomic():
            connection.ensure_connection()
            logger.debug(f"[TASK_scan_sbom_for_vulnerabilities] Attempting to fetch SBOM ID: {sbom_id} from database.")
            sbom_instance = SBOM.objects.get(id=sbom_id)
            logger.debug(
                f"[TASK_scan_sbom_for_vulnerabilities] SBOM ID: {sbom_id} fetched. "
                f"Filename: {sbom_instance.sbom_filename}"
            )

        if not sbom_instance.sbom_filename:
            logger.error(f"[TASK_scan_sbom_for_vulnerabilities] SBOM ID: {sbom_id} has no sbom_filename.")
            return {"error": f"SBOM ID: {sbom_id} has no sbom_filename."}

        # 2. Download SBOM from S3
        logger.debug(f"[TASK_scan_sbom_for_vulnerabilities] Downloading SBOM {sbom_instance.sbom_filename} from S3.")
        s3_client = S3Client(bucket_type="SBOMS")
        sbom_data_bytes = s3_client.get_sbom_data(sbom_instance.sbom_filename)

        if not sbom_data_bytes:
            logger.error(
                f"[TASK_scan_sbom_for_vulnerabilities] Failed to download SBOM "
                f"{sbom_instance.sbom_filename} from S3 (empty data)."
            )
            return {"error": f"Failed to download SBOM {sbom_instance.sbom_filename} from S3 (empty data)."}

        logger.debug(
            f"[TASK_scan_sbom_for_vulnerabilities] Downloaded {len(sbom_data_bytes)} bytes "
            f"for {sbom_instance.sbom_filename}."
        )

        # Attempt to parse as JSON to check basic integrity
        try:
            json.loads(sbom_data_bytes.decode("utf-8"))
            logger.debug(
                f"[TASK_scan_sbom_for_vulnerabilities] SBOM {sbom_instance.sbom_filename} "
                f"successfully parsed as JSON."
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(
                f"[TASK_scan_sbom_for_vulnerabilities] SBOM {sbom_instance.sbom_filename} "
                f"is not valid JSON or has encoding issues. Error: {e}. "
                f"First 200 chars: {sbom_data_bytes[:200]}"
            )
            return {
                "error": (f"SBOM {sbom_instance.sbom_filename} content is not valid JSON " f"or has encoding issues."),
                "details": str(e),
            }

        file_suffix = ".json"  # Default
        if sbom_instance.format:
            if "cyclonedx" in sbom_instance.format.lower():
                file_suffix = ".cdx.json"
            elif "spdx" in sbom_instance.format.lower():
                file_suffix = ".spdx.json"

        with tempfile.NamedTemporaryFile(delete=False, mode="wb", suffix=file_suffix) as temp_file:
            temp_sbom_file = temp_file.name
            temp_file.write(sbom_data_bytes)  # Write the original bytes

        # Execute osv-scanner
        osv_scanner_path = "/usr/local/bin/osv-scanner"  # As defined in Dockerfile
        scan_command = [
            osv_scanner_path,
            "scan",
            "source",  # Using "scan source" as it worked in local tests
            "--sbom",
            temp_sbom_file,
            "--format",
            "json",
        ]
        scan_command_str = " ".join(scan_command)
        logger.debug(f"[OSV_SCAN] Executing command: {scan_command_str}")

        try:
            process = subprocess.run(scan_command, capture_output=True, text=True)

            stderr_content = process.stderr.strip() if process.stderr else ""

            if stderr_content:
                if process.returncode == 0 or process.returncode == 1:  # Success or success with findings
                    lines = stderr_content.split("\n")
                    is_purely_informational = all(
                        not line.strip()
                        or "Neither CPE nor PURL found for package" in line
                        or ("Filtered" in line and "package/s from the scan" in line)
                        or ("Scanned" in line and "file and found" in line and "package" in line)
                        for line in lines
                    )
                    if is_purely_informational:
                        logger.debug(
                            f"[TASK_scan_sbom_for_vulnerabilities] osv-scanner info for SBOM ID {sbom_id} "
                            f"(code {process.returncode}): {stderr_content}"
                        )
                    else:
                        logger.warning(
                            f"[TASK_scan_sbom_for_vulnerabilities] osv-scanner stderr for SBOM ID {sbom_id} "
                            f"(code {process.returncode}): {stderr_content}"
                        )
                else:  # Bad exit code (neither 0 nor 1), but there was stderr
                    logger.warning(
                        f"[TASK_scan_sbom_for_vulnerabilities] osv-scanner failure context for SBOM ID {sbom_id} "
                        f"(code {process.returncode}): {stderr_content}"
                    )

            # For non-zero exit codes that are not 1 (vulns found), raise the exception
            if process.returncode != 0 and process.returncode != 1:
                raise subprocess.CalledProcessError(
                    process.returncode, scan_command_str, process.stdout, process.stderr
                )

            logger.info(f"[TASK_scan_sbom_for_vulnerabilities] Completed vulnerability scan for SBOM ID: {sbom_id}")

            # Store results in Redis
            redis_client = dramatiq.get_broker().client
            redis_client.set(
                f"osv_scan_result:{sbom_id}:{datetime.now(timezone.utc).isoformat()}",
                process.stdout,
                ex=86400,  # 24 hours
            )
            logger.debug(f"[TASK_scan_sbom_for_vulnerabilities] Scan results for SBOM ID {sbom_id} stored in Redis")

        finally:
            # 5. Clean up temporary file
            if os.path.exists(temp_sbom_file):
                os.remove(temp_sbom_file)
                logger.debug(f"[TASK_scan_sbom_for_vulnerabilities] Cleaned up temporary file: {temp_sbom_file}")

        return {
            "sbom_id": sbom_id,
            "status": "Scan completed.",
            "message": "Scan successful, results stored in Redis.",
            "scan_output_preview": json.loads(process.stdout).get("results", [])[:1]
            if process.stdout
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
            f"[TASK_scan_sbom_for_vulnerabilities] Database error occurred processing " f"SBOM ID {sbom_id}: {db_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except ConnectionError as conn_err:  # General connection error
        logger.error(
            f"[TASK_scan_sbom_for_vulnerabilities] Connection error occurred processing "
            f"SBOM ID {sbom_id}: {conn_err}",
            exc_info=True,
        )
        raise  # Re-raise to allow tenacity to handle retries
    except Exception as e:
        logger.error(
            f"[TASK_scan_sbom_for_vulnerabilities] An unexpected error occurred processing " f"SBOM ID {sbom_id}: {e}",
            exc_info=True,
        )
        # For unexpected errors, it's often better to let Dramatiq handle retries if configured.
        raise


# Example task for testing
@dramatiq.actor
def example_task(message: str):
    logger.info(f"Processing message: {message}")
