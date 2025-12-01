import logging
from typing import Any, Dict

from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.ntia_validator import (
    NTIAComplianceStatus,
    validate_sbom_ntia_compliance,
)
from sbomify.apps.sboms.utils import SBOMDataError, get_sbom_data, serialize_validation_errors
from sbomify.task_utils import format_task_error, sbom_processing_task

logger = logging.getLogger(__name__)


@sbom_processing_task()
def check_sbom_ntia_compliance(sbom_id: str) -> Dict[str, Any]:
    """
    Validate an SBOM against NTIA minimum elements and persist the results.

    Returns a dict with keys: sbom_id, status, compliance_status, is_compliant, error_count, message.
    """
    logger.info(f"[TASK_check_sbom_ntia_compliance] Starting NTIA compliance check for SBOM ID: {sbom_id}")

    try:
        # 1) Fetch SBOM data using shared utility
        sbom_instance, sbom_data = get_sbom_data(sbom_id)

        # 2) Validate using NTIA validator
        validation = validate_sbom_ntia_compliance(sbom_data, sbom_instance.format)
        is_compliant = bool(getattr(validation, "is_compliant", False))
        status_value = (
            validation.status.value if isinstance(validation.status, NTIAComplianceStatus) else str(validation.status)
        )
        error_count = int(getattr(validation, "error_count", len(getattr(validation, "errors", []))))

        # 3) Build JSON-serializable details using shared utility
        details: Dict[str, Any] = {
            "is_compliant": is_compliant,
            "status": status_value,
            "errors": serialize_validation_errors(getattr(validation, "errors", [])),
            "checked_at": getattr(validation, "checked_at", None).isoformat()
            if getattr(validation, "checked_at", None)
            else None,
        }

        # 4) Persist results
        from django.utils import timezone as django_timezone

        sbom_update = SBOM.objects.select_for_update().get(id=sbom_id)
        if status_value == NTIAComplianceStatus.UNKNOWN.value:
            sbom_update.ntia_compliance_status = SBOM.NTIAComplianceStatus.UNKNOWN
        else:
            sbom_update.ntia_compliance_status = (
                SBOM.NTIAComplianceStatus.COMPLIANT if is_compliant else SBOM.NTIAComplianceStatus.NON_COMPLIANT
            )
        sbom_update.ntia_compliance_details = details
        sbom_update.ntia_compliance_checked_at = django_timezone.now()
        sbom_update.save()

        logger.info(
            f"[TASK_check_sbom_ntia_compliance] NTIA compliance check completed for SBOM ID: {sbom_id}. "
            f"Status: {status_value}, Errors: {error_count}"
        )

        return {
            "sbom_id": str(sbom_id),
            "status": "NTIA compliance check completed",
            "compliance_status": status_value,
            "is_compliant": is_compliant,
            "error_count": error_count,
            "message": "Validation completed",
        }

    except SBOMDataError as e:
        return format_task_error("check_sbom_ntia_compliance", sbom_id, str(e))
