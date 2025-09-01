import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.errors import error_response
from core.object_store import S3Client
from core.utils import verify_item_access
from teams.schemas import BrandingInfo

from .forms import DocumentMetadataForm
from .models import Document

logger = logging.getLogger(__name__)


@login_required
def document_details_private(request: HttpRequest, document_id: str) -> HttpResponse:
    try:
        document: Document = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Document not found"))

    if not verify_item_access(request, document.component, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    return render(
        request,
        "documents/document_details_private.html.j2",
        {"document": document, "APP_BASE_URL": settings.APP_BASE_URL},
    )


def document_details_public(request: HttpRequest, document_id: str) -> HttpResponse:
    try:
        document: Document = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Document not found"))

    if not document.public_access_allowed:
        return error_response(request, HttpResponseForbidden("Document is not public"))

    branding_info = BrandingInfo(**document.component.team.branding_info)

    return render(
        request,
        "documents/document_details_public.html.j2",
        {"document": document, "brand": branding_info, "APP_BASE_URL": settings.APP_BASE_URL},
    )


# Removed update_document_field view - using full metadata edit form instead


def document_download(request: HttpRequest, document_id: str) -> HttpResponse:
    """Download a document file."""
    try:
        document: Document = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Document not found"))

    # Check access permissions
    if document.public_access_allowed or (
        request.user.is_authenticated and verify_item_access(request, document.component, ["guest", "owner", "admin"])
    ):
        try:
            s3 = S3Client("DOCUMENTS")
            document_data = s3.get_document_data(document.document_filename)

            if document_data:
                response = HttpResponse(document_data, content_type=document.content_type or "application/octet-stream")
                # Use original filename if available, otherwise use document name
                filename = document.name if document.name else f"document_{document.id}"
                response["Content-Disposition"] = f'attachment; filename="{filename}"'
                return response
            else:
                return error_response(request, HttpResponseNotFound("Document file not found"))

        except Exception as e:
            logger.exception(f"Error retrieving document: {str(e)}")
            return error_response(request, HttpResponse("Error retrieving document", status=500))
    else:
        return error_response(request, HttpResponseForbidden("Access denied"))


@login_required
def document_metadata_edit(request: HttpRequest, document_id: str) -> HttpResponse:
    """Edit document metadata."""
    document = get_object_or_404(Document, pk=document_id)

    # Check permissions
    if not verify_item_access(request, document.component, ["owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only owners and admins can edit document metadata"))

    if request.method == "POST":
        form = DocumentMetadataForm(request.POST, instance=document)
        if form.is_valid():
            form.save()
            messages.success(request, f"Document metadata updated successfully!")
            return redirect("documents:document_details", document_id=document.id)
    else:
        form = DocumentMetadataForm(instance=document)

    context = {
        "document": document,
        "form": form,
        "component": document.component,
    }

    return render(request, "documents/document_metadata_edit.html.j2", context)
