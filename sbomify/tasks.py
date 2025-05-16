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

# Set up Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sbomify.settings")
import django  # noqa: E402

django.setup()

import tempfile  # noqa: E402

from django.conf import settings  # noqa: E402

from core.object_store import S3Client  # noqa: E402
from sboms.models import SBOM  # noqa: E402
from sboms.schemas import DBSBOMLicense  # noqa: E402

# Configure Dramatiq
if not (getattr(settings, "TESTING", False) or os.environ.get("PYTEST_CURRENT_TEST")):
    redis_broker = RedisBroker(url=settings.REDIS_WORKER_URL)
    result_backend = RedisBackend(url=settings.REDIS_WORKER_URL)
    redis_broker.add_middleware(Results(backend=result_backend))
    dramatiq.set_broker(redis_broker)

logger = logging.getLogger(__name__)


@dramatiq.actor(queue_name="sbom_license_processing", max_retries=3, time_limit=300000, store_results=True)
def process_sbom_licenses(sbom_id: str) -> Dict[str, Any]:
    """
    Process and analyze license data from an SBOM asynchronously.
    This now also extracts and populates the packages_licenses field from the SBOM file or data.
    """
    logger.info(f"[TASK_process_sbom_licenses] Received task for SBOM ID: {sbom_id}")
    try:
        with transaction.atomic():
            logger.info(f"[TASK_process_sbom_licenses] Attempting to fetch SBOM ID: {sbom_id} from database.")
            sbom = SBOM.objects.select_for_update().get(id=sbom_id)
            logger.info(
                (
                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} fetched. "
                    f"Format: {sbom.format}, Filename: {sbom.sbom_filename}"
                )
            )

            # Try to load SBOM data from file or data field
            sbom_data = None
            if hasattr(sbom, "data") and sbom.data:
                logger.info(
                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Attempting to load from sbom.data field."
                )
                sbom_data = sbom.data
            elif sbom.sbom_filename:
                logger.info(
                    (
                        f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Attempting to load from "
                        f"sbom_filename: {sbom.sbom_filename} via S3."
                    )
                )
                s3_client = S3Client("SBOMS")
                try:
                    # Create a temporary file to download the SBOM content
                    with tempfile.NamedTemporaryFile(
                        mode="wb", delete=False, suffix=".json"
                    ) as tmp_file_obj:  # Open in 'wb' for download_file
                        tmp_file_path = tmp_file_obj.name
                    # download_file expects a path, not a file object, so we close the temp
                    # file first (it remains due to delete=False) then S3 can write to it.
                    logger.info(
                        (
                            f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Downloading S3 object "
                            f"{sbom.sbom_filename} "
                            f"to temporary file: "
                            f"{tmp_file_path}"
                        )
                    )
                    s3_client.download_file(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, sbom.sbom_filename, tmp_file_path)
                    logger.info(
                        (
                            f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Successfully downloaded SBOM "
                            f"from S3 to temporary file: {tmp_file_path}"
                        )
                    )

                    with open(tmp_file_path, "r") as f:  # Open in 'r' mode for json.load
                        import json

                        sbom_data = json.load(f)
                    logger.info(
                        (
                            f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - "
                            f"Successfully loaded and parsed JSON from temporary file."
                        )
                    )

                    # Clean up the temporary file
                    os.unlink(tmp_file_path)
                    logger.info(
                        (
                            f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - "
                            f"Cleaned up temporary file: {tmp_file_path}"
                        )
                    )

                except Exception as s3_error:
                    logger.error(
                        (
                            f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id}"
                            f"- Error downloading/processing SBOM from S3: {s3_error}"
                        ),
                        exc_info=True,
                    )
                    sbom_data = None  # Ensure sbom_data is None if S3 operations fail
            else:
                logger.warning(
                    (
                        f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - No sbom.data and no "
                        f"sbom.sbom_filename. Cannot load SBOM content."
                    )
                )

            packages_licenses = {}
            if sbom_data:
                logger.info(
                    (
                        f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - "
                        f"SBOM data loaded, proceeding with license extraction."
                    )
                )
                # CycloneDX
                if sbom.format == "cyclonedx":
                    logger.info(f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Processing as CycloneDX format.")
                    for comp_idx, comp in enumerate(sbom_data.get("components", [])):
                        comp_name = comp.get("name", f"UnnamedComponent_{comp_idx}")
                        logger.info(
                            (
                                f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Processing "
                                f"CycloneDX component: {comp_name}"
                            )
                        )
                        if "licenses" in comp:
                            licenses = []
                            for lic_info_idx, license_info in enumerate(comp["licenses"]):
                                if "license" in license_info:
                                    l_dict = license_info["license"]
                                    logger.debug(
                                        (
                                            f"[TASK_process_sbom_licenses] SBOM ID: "
                                            f"{sbom_id} - Component {comp_name} - "
                                            f"Raw license data: {l_dict}"
                                        )
                                    )
                                    # Handle invalid long license names
                                    if "name" in l_dict and isinstance(l_dict["name"], str):
                                        l_dict["name"] = l_dict["name"].split("\n")[0]
                                    try:
                                        parsed_license = DBSBOMLicense(**l_dict).model_dump(exclude_none=True)
                                        licenses.append(parsed_license)
                                        logger.debug(
                                            (
                                                f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id}"
                                                f" - Component {comp_name} - "
                                                f"Parsed license: {parsed_license}"
                                            )
                                        )
                                    except Exception as lic_parse_err:
                                        logger.error(
                                            (
                                                f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} "
                                                f"- Component {comp_name} - "
                                                f"Error parsing license_info {l_dict}: "
                                                f"{lic_parse_err}"
                                            )
                                        )
                                else:
                                    logger.warning(
                                        (
                                            f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} "
                                            f"- Component {comp_name} - "
                                            f"license_info item {lic_info_idx} does not contain "
                                            f"'license' key: {license_info}"
                                        )
                                    )
                            if licenses:
                                packages_licenses[comp_name] = licenses
                                logger.info(
                                    (
                                        f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Component {comp_name} - "
                                        f"Added {len(licenses)} licenses."
                                    )
                                )
                        else:
                            logger.info(
                                (
                                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - "
                                    f"Component {comp_name} - No 'licenses' field found."
                                )
                            )
                # SPDX
                elif sbom.format == "spdx":
                    logger.info(f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Processing as SPDX format.")
                    for pkg_idx, pkg in enumerate(sbom_data.get("packages", [])):
                        pkg_name = pkg.get("name", f"UnnamedPackage_{pkg_idx}")
                        logger.info(
                            (
                                f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - "
                                f"Processing SPDX package: {pkg_name}"
                            )
                        )
                        licenses = []
                        if "licenseConcluded" in pkg and pkg["licenseConcluded"] != "NOASSERTION":
                            license_id_val = pkg["licenseConcluded"]
                            licenses.append({"id": license_id_val})
                            logger.debug(
                                (
                                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - "
                                    f"Package {pkg_name} - Found licenseConcluded: {license_id_val}"
                                )
                            )
                        if (
                            licenses
                        ):  # SPDX structure stores one licenseConcluded, this check might be redundant if only one
                            packages_licenses[pkg_name] = licenses
                            logger.info(
                                (
                                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Package {pkg_name} - "
                                    f"Added license: {licenses}"
                                )
                            )
                        else:
                            logger.info(
                                (
                                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Package {pkg_name} - "
                                    f"No valid 'licenseConcluded' found or was NOASSERTION."
                                )
                            )
                else:
                    logger.warning(
                        (
                            f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Unknown SBOM format: {sbom.format}. "
                            f"Cannot extract package licenses."
                        )
                    )
            else:
                logger.warning(
                    (
                        f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - sbom_data is empty. "
                        f"Skipping package license extraction."
                    )
                )

            # Save extracted package licenses
            logger.info(
                (
                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Final packages_licenses "
                    f"to be saved: {packages_licenses}"
                )
            )
            sbom.packages_licenses = packages_licenses

            # Store original license data for analysis
            original_licenses = sbom.licenses
            original_packages_licenses = sbom.packages_licenses

            # Initialize results
            results = {
                "sbom_id": sbom_id,
                "total_licenses": 0,
                "spdx_licenses": [],
                "custom_licenses": [],
                "license_categories": {"permissive": [], "copyleft": [], "proprietary": [], "unknown": []},
                "original_licenses": original_licenses,
                "original_packages_licenses": original_packages_licenses,
            }

            # Process main SBOM licenses
            for license_info in original_licenses:
                results["total_licenses"] += 1

                if isinstance(license_info, dict):
                    if "id" in license_info:
                        # SPDX license
                        license_id = license_info["id"]
                        results["spdx_licenses"].append(license_id)

                        # Categorize license
                        if license_id in ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC"]:
                            results["license_categories"]["permissive"].append(license_id)
                        elif "GPL" in license_id or "AGPL" in license_id:
                            results["license_categories"]["copyleft"].append(license_id)
                        else:
                            results["license_categories"]["unknown"].append(license_id)
                    else:
                        # Custom license
                        results["custom_licenses"].append(license_info)
                        results["license_categories"]["unknown"].append(license_info.get("name", "Unknown"))
                elif isinstance(license_info, str):
                    # Handle string license identifiers (common in SPDX)
                    results["spdx_licenses"].append(license_info)
                    if license_info in ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC"]:
                        results["license_categories"]["permissive"].append(license_info)
                    elif "GPL" in license_info or "AGPL" in license_info:
                        results["license_categories"]["copyleft"].append(license_info)
                    else:
                        results["license_categories"]["unknown"].append(license_info)

            # Process package licenses
            for package_name, package_licenses in original_packages_licenses.items():
                for license_info in package_licenses:
                    results["total_licenses"] += 1

                    if isinstance(license_info, dict):
                        if "id" in license_info:
                            # SPDX license
                            license_id = license_info["id"]
                            results["spdx_licenses"].append(license_id)

                            # Categorize license
                            if license_id in ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC"]:
                                results["license_categories"]["permissive"].append(license_id)
                            elif "GPL" in license_id or "AGPL" in license_id:
                                results["license_categories"]["copyleft"].append(license_id)
                            else:
                                results["license_categories"]["unknown"].append(license_id)
                        else:
                            # Custom license
                            results["custom_licenses"].append(license_info)
                            results["license_categories"]["unknown"].append(license_info.get("name", "Unknown"))
                    elif isinstance(license_info, str):
                        # Handle string license identifiers
                        results["spdx_licenses"].append(license_info)
                        if license_info in ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC"]:
                            results["license_categories"]["permissive"].append(license_info)
                        elif "GPL" in license_info or "AGPL" in license_info:
                            results["license_categories"]["copyleft"].append(license_info)
                        else:
                            results["license_categories"]["unknown"].append(license_info)

            # Remove duplicates
            for category in results["license_categories"]:
                results["license_categories"][category] = list(set(results["license_categories"][category]))

            results["spdx_licenses"] = list(set(results["spdx_licenses"]))

            # Store the analysis results in the licenses field
            sbom.licenses = results
            sbom.save()  # This save will commit both licenses and packages_licenses due to transaction
            logger.info(
                (
                    f"[TASK_process_sbom_licenses] SBOM ID: {sbom_id} - Successfully processed and saved "
                    f"license analysis. Result: {results}"
                )
            )

            return results

    except SBOM.DoesNotExist:
        logger.error(f"[TASK_process_sbom_licenses] SBOM with ID {sbom_id} not found.")
        return {"error": f"SBOM with ID {sbom_id} not found"}
    except Exception as e:
        logger.error(
            f"[TASK_process_sbom_licenses] Error processing SBOM ID {sbom_id}: {e}", exc_info=True
        )  # Add exc_info for traceback
        return {"error": str(e)}


# Example task for testing
@dramatiq.actor
def example_task(message: str):
    logger.info(f"Processing message: {message}")
