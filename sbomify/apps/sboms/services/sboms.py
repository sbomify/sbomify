from __future__ import annotations

import logging

from django.conf import settings
from django.http import HttpRequest

from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.sboms.models import SBOM

log = logging.getLogger(__name__)


def delete_sbom_record(request: HttpRequest, sbom_id: str) -> ServiceResult[None]:
    try:
        sbom = SBOM.objects.get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return ServiceResult.failure("SBOM not found", status_code=404)

    if not verify_item_access(request, sbom.component, ["owner", "admin"]):
        return ServiceResult.failure("Only owners or admins of the component can delete SBOMs", status_code=403)

    if sbom.sbom_filename:
        try:
            s3 = S3Client("SBOMS")
            s3.delete_object(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, sbom.sbom_filename)
        except Exception as exc:
            log.warning(f"Failed to delete SBOM file {sbom.sbom_filename} from S3: {exc}")

    sbom.delete()

    return ServiceResult.success()


def serialize_sbom(sbom: SBOM) -> dict:
    return {
        "id": str(sbom.id),
        "name": sbom.name,
        "version": sbom.version,
        "format": sbom.format,
        "format_version": sbom.format_version,
        "sbom_filename": sbom.sbom_filename,
        "created_at": sbom.created_at,
        "source": sbom.source,
        "component_id": str(sbom.component.id),
        "component_name": sbom.component.name,
        "source_display": sbom.source_display,
    }


def get_sbom_detail(request: HttpRequest, sbom_id: str) -> ServiceResult[dict]:
    try:
        sbom = SBOM.objects.select_related("component").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return ServiceResult.failure("SBOM not found", status_code=404)

    if not sbom.component.is_public:
        if not verify_item_access(request, sbom.component, ["guest", "owner", "admin"]):
            return ServiceResult.failure("Forbidden", status_code=403)

    return ServiceResult.success(serialize_sbom(sbom))
