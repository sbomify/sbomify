import logging

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.documents.models import Document

logger = logging.getLogger(__name__)


class DocumentDownloadView(View):
    def get(self, request: HttpRequest, document_id: str) -> HttpResponse:
        try:
            document: Document = Document.objects.get(pk=document_id)
        except Document.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Document not found"))

        if document.public_access_allowed or (
            request.user.is_authenticated
            and verify_item_access(request, document.component, ["guest", "owner", "admin"])
        ):
            try:
                s3 = S3Client("DOCUMENTS")
                document_data = s3.get_document_data(document.document_filename)

                if document_data:
                    response = HttpResponse(
                        document_data, content_type=document.content_type or "application/octet-stream"
                    )
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
