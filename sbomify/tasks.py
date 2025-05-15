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

from django.conf import settings  # noqa: E402

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
    try:
        with transaction.atomic():
            sbom = SBOM.objects.select_for_update().get(id=sbom_id)

            # Try to load SBOM data from file or data field
            sbom_data = None
            if hasattr(sbom, "data") and sbom.data:
                sbom_data = sbom.data
            elif sbom.sbom_filename:
                # Try to load from file (assume local file for now)
                sbom_path = os.path.join("/code", "sboms", "sbom_files", sbom.sbom_filename)
                if os.path.exists(sbom_path):
                    import json

                    with open(sbom_path) as f:
                        sbom_data = json.load(f)

            packages_licenses = {}
            # CycloneDX
            if sbom.format == "cyclonedx" and sbom_data:
                for comp in sbom_data.get("components", []):
                    if "licenses" in comp:
                        licenses = []
                        for license_info in comp["licenses"]:
                            if "license" in license_info:
                                l_dict = license_info["license"]
                                # Handle invalid long license names
                                if "name" in l_dict:
                                    l_dict["name"] = l_dict["name"].split("\n")[0]
                                licenses.append(DBSBOMLicense(**l_dict).model_dump(exclude_none=True))
                        if licenses:
                            packages_licenses[comp.get("name", "")] = licenses
            # SPDX
            elif sbom.format == "spdx" and sbom_data:
                for pkg in sbom_data.get("packages", []):
                    licenses = []
                    if "licenseConcluded" in pkg and pkg["licenseConcluded"] != "NOASSERTION":
                        licenses.append({"id": pkg["licenseConcluded"]})
                    if licenses:
                        packages_licenses[pkg.get("name", "")] = licenses

            # Save extracted package licenses
            sbom.packages_licenses = packages_licenses
            sbom.save()

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
            sbom.save()

            return results

    except SBOM.DoesNotExist:
        return {"error": f"SBOM with ID {sbom_id} not found"}
    except Exception as e:
        return {"error": str(e)}


# Example task for testing
@dramatiq.actor
def example_task(message: str):
    logger.info(f"Processing message: {message}")
