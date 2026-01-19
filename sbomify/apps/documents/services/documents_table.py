from __future__ import annotations

import json

from django.http import HttpRequest

from sbomify.apps.core.apis import get_component, list_component_documents
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.documents.forms import DocumentDeleteForm, DocumentEditForm
from sbomify.apps.documents.models import Document
from sbomify.apps.documents.schemas import DocumentUpdateRequest
from sbomify.apps.documents.services.documents import delete_document_record, update_document_metadata


def build_documents_table_context(request: HttpRequest, component_id: str, is_public_view: bool) -> ServiceResult[dict]:
    status_code, component = get_component(request, component_id)
    if status_code != 200:
        return ServiceResult.failure(component.get("detail", "Unknown error"))

    status_code, documents = list_component_documents(request, component_id, page=1, page_size=-1)
    if status_code != 200:
        return ServiceResult.failure(documents.get("detail", "Failed to load documents"))

    # Build mapping of document types to their subcategory choices
    # This allows dynamic subcategory dropdowns based on document type
    document_type_subcategories = {}
    for doc_type_value, doc_type_label in Document.DocumentType.choices:
        if doc_type_value == Document.DocumentType.COMPLIANCE:
            document_type_subcategories[doc_type_value] = {
                "field_name": "compliance_subcategory",
                "choices": Document.ComplianceSubcategory.choices,
                "label": "Compliance Subcategory",
            }
        # Add more document types with subcategories here as needed
        # Example:
        # elif doc_type_value == Document.DocumentType.OTHER_TYPE:
        #     document_type_subcategories[doc_type_value] = {
        #         "field_name": "other_subcategory",  # Use a specific field name for that type
        #         "choices": Document.OtherSubcategory.choices,
        #         "label": "Subcategory"
        #     }

    context = {
        "component_id": component_id,
        "documents": documents.get("items"),
        "is_public_view": is_public_view,
        "has_crud_permissions": component.get("has_crud_permissions") if not is_public_view else False,
        "delete_form": DocumentDeleteForm(),
        "document_type_choices": Document.DocumentType.choices,
        "document_type_subcategories": document_type_subcategories,
        "document_type_subcategories_json": json.dumps(document_type_subcategories),
    }

    return ServiceResult.success(context)


def delete_document_from_request(request: HttpRequest) -> ServiceResult[None]:
    form = DocumentDeleteForm(request.POST)
    if not form.is_valid():
        return ServiceResult.failure(form.errors.as_text())

    document_id = form.cleaned_data["document_id"]
    result = delete_document_record(request, document_id)
    if not result.ok:
        return ServiceResult.failure(result.error or "Failed to delete document", status_code=result.status_code)

    return ServiceResult.success()


def update_document_from_request(request: HttpRequest) -> ServiceResult[None]:
    form = DocumentEditForm(request.POST)
    if not form.is_valid():
        return ServiceResult.failure(form.errors.as_text())

    document_id = form.cleaned_data["document_id"]
    document_type = form.cleaned_data.get("document_type")

    # Dynamically extract subcategory based on document type
    compliance_subcategory = None
    if document_type == Document.DocumentType.COMPLIANCE:
        # Get compliance_subcategory from form or POST data
        compliance_subcategory = (
            form.cleaned_data.get("compliance_subcategory") or request.POST.get("compliance_subcategory") or None
        )
    # Add more subcategory fields here as needed for other document types

    payload = DocumentUpdateRequest(
        name=form.cleaned_data.get("name"),
        version=form.cleaned_data.get("version"),
        document_type=document_type,
        compliance_subcategory=compliance_subcategory,
        description=form.cleaned_data.get("description"),
    )

    result = update_document_metadata(request, document_id, payload)
    if not result.ok:
        return ServiceResult.failure(result.error or "Failed to update document", status_code=result.status_code)

    return ServiceResult.success()
