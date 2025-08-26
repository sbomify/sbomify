import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from core.errors import error_response
from core.object_store import S3Client
from core.utils import verify_item_access
from teams.schemas import BrandingInfo

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


@login_required
@require_http_methods(["POST"])
def update_document_field(request: HttpRequest, document_id: str) -> JsonResponse:
    """Update a single field of a document"""
    try:
        document: Document = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return JsonResponse({"error": "Document not found"}, status=404)

    if not verify_item_access(request, document.component, ["owner", "admin"]):
        return JsonResponse({"error": "Permission denied"}, status=403)

    try:
        data = json.loads(request.body)
        field = data.get("field")
        value = data.get("value", "").strip()

        if field == "description":
            document.description = value
            document.save()
            return JsonResponse(
                {"success": True, "message": "Description updated successfully", "value": document.description}
            )
        elif field == "version":
            document.version = value
            document.save()
            return JsonResponse({"success": True, "message": "Version updated successfully", "value": document.version})
        else:
            return JsonResponse({"error": "Invalid field"}, status=400)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON data"}, status=400)
    except Exception as e:
        logger.error(f"Error updating document {document_id}: {e}")
        return JsonResponse({"error": "Internal server error"}, status=500)


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
