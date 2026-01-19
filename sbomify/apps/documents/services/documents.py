from __future__ import annotations

import logging

from django.http import HttpRequest

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.documents.models import Document
from sbomify.apps.documents.schemas import DocumentUpdateRequest

log = logging.getLogger(__name__)


def serialize_document(document: Document) -> dict:
    return {
        "id": document.id,
        "name": document.name,
        "version": document.version,
        "document_filename": document.document_filename,
        "created_at": document.created_at,
        "source": document.source,
        "component_id": document.component.id,
        "component_name": document.component.name,
        "document_type": document.document_type,
        "description": document.description,
        "content_type": document.content_type,
        "file_size": document.file_size,
        "source_display": document.source_display,
    }


def get_document_detail(request: HttpRequest, document_id: str) -> ServiceResult[dict]:
    try:
        document = Document.objects.select_related("component").get(pk=document_id)
    except Document.DoesNotExist:
        return ServiceResult.failure("Document not found", status_code=404)

    component = document.component

    # Use centralized access control
    from sbomify.apps.core.services.access_control import check_component_access

    access_result = check_component_access(request, component)

    if not access_result.has_access:
        return ServiceResult.failure("Forbidden", status_code=403)

    return ServiceResult.success(serialize_document(document))


def update_document_metadata(
    request: HttpRequest, document_id: str, payload: DocumentUpdateRequest
) -> ServiceResult[dict]:
    try:
        document = Document.objects.select_related("component").get(pk=document_id)
    except Document.DoesNotExist:
        return ServiceResult.failure("Document not found", status_code=404)

    if not verify_item_access(request, document.component, ["owner", "admin"]):
        return ServiceResult.failure("Only owners and admins can update documents", status_code=403)

    update_fields = []
    if payload.name is not None:
        document.name = payload.name
        update_fields.append("name")
    if payload.version is not None:
        document.version = payload.version
        update_fields.append("version")
    if payload.document_type is not None:
        document.document_type = payload.document_type
        update_fields.append("document_type")
        # Clear compliance_subcategory if document_type is not compliance
        if payload.document_type != Document.DocumentType.COMPLIANCE:
            document.compliance_subcategory = None
            update_fields.append("compliance_subcategory")
    if payload.compliance_subcategory is not None:
        document.compliance_subcategory = payload.compliance_subcategory if payload.compliance_subcategory else None
        update_fields.append("compliance_subcategory")
    if payload.description is not None:
        document.description = payload.description
        update_fields.append("description")

    if update_fields:
        document.save(update_fields=update_fields)

    return ServiceResult.success(serialize_document(document))


def delete_document_record(request: HttpRequest, document_id: str) -> ServiceResult[None]:
    try:
        document = Document.objects.select_related("component").get(pk=document_id)
    except Document.DoesNotExist:
        return ServiceResult.failure("Document not found", status_code=404)

    if not verify_item_access(request, document.component, ["owner", "admin"]):
        return ServiceResult.failure("Only owners and admins can delete documents", status_code=403)

    try:
        document.delete()
        return ServiceResult.success()
    except Exception as exc:
        log.error(f"Error deleting document {document_id}: {exc}")
        return ServiceResult.failure("Invalid request", status_code=400)
