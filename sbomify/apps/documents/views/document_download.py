import logging

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.services.access_control import check_component_access
from sbomify.apps.documents.models import Document

logger = logging.getLogger(__name__)


class DocumentDownloadView(View):
    def get(self, request: HttpRequest, document_id: str) -> HttpResponse:
        try:
            document: Document = Document.objects.get(pk=document_id)
        except Document.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Document not found"))

        # Check access permissions using centralized access control
        component = document.component
        access_result = check_component_access(request, component)

        if access_result.has_access:
            try:
                s3 = S3Client("DOCUMENTS")
                document_data = s3.get_document_data(document.document_filename)

                if document_data:
                    response = HttpResponse(
                        document_data, content_type=document.content_type or "application/octet-stream"
                    )
                    # Use original filename if available, otherwise use document name
                    filename = document.name if document.name else f"document_{document.id}"

                    # Check if inline view is requested
                    disposition_type = "inline" if request.GET.get("view") == "inline" else "attachment"
                    response["Content-Disposition"] = f'{disposition_type}; filename="{filename}"'

                    # Allow embedding in iframe if inline view
                    if disposition_type == "inline":
                        response["X-Frame-Options"] = "SAMEORIGIN"

                    return response
                else:
                    return error_response(request, HttpResponseNotFound("Document file not found"))

            except Exception as e:
                from botocore.exceptions import ClientError

                # Check if it's a NoSuchKey error (file doesn't exist in S3)
                if isinstance(e, ClientError):
                    error_code = e.response.get("Error", {}).get("Code", "")
                    if error_code == "NoSuchKey":
                        logger.error(
                            f"Document file {document.document_filename} not found in S3 for document {document.id}. "
                            f"The database record exists but the file is missing."
                        )
                        return error_response(
                            request,
                            HttpResponseNotFound("Document file not found in storage. The file may have been deleted."),
                        )

                # For other errors, log and return generic error
                logger.exception(f"Error retrieving document {document.id}: {str(e)}")
                return error_response(request, HttpResponse("Error retrieving document", status=500))
        else:
            # Check if this is a request from a public page (via query param or session)
            # Using query param is more reliable than HTTP_REFERER which can be spoofed/absent
            is_from_public_page = request.GET.get("from_public") == "true" or request.session.get(
                "viewing_public_component"
            ) == str(component.id)

            # Provide helpful error message for gated components
            if component.visibility == component.Visibility.GATED:
                if is_from_public_page:
                    # Return a simple HTML page with message and redirect back
                    from django.shortcuts import render
                    from django.urls import reverse

                    team = component.team
                    error_message = (
                        "Please request access to download this document."
                        if not request.user.is_authenticated
                        else "Your access request is pending approval or has been rejected."
                    )
                    request_access_url = (
                        reverse("documents:request_access", kwargs={"team_key": team.key}) if team else None
                    )

                    # Get component detail page URL instead of referrer to avoid loops
                    component_detail_url = reverse(
                        "core:component_details_public", kwargs={"component_id": component.id}
                    )

                    return render(
                        request,
                        "core/access_denied_message.html.j2",
                        {
                            "error_message": error_message,
                            "request_access_url": request_access_url,
                            "back_url": component_detail_url,
                            "item_type": "document",
                        },
                        status=403,
                    )

                if not request.user.is_authenticated:
                    return error_response(
                        request,
                        HttpResponseForbidden("Access denied. Please request access to download this document."),
                    )
                else:
                    return error_response(
                        request,
                        HttpResponseForbidden(
                            "Access denied. Your access request is pending approval or has been rejected."
                        ),
                    )
            return error_response(request, HttpResponseForbidden("Access denied"))
