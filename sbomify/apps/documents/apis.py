import hashlib
import logging
import mimetypes

from django.db import transaction
from django.http import HttpRequest, HttpResponse
from ninja import File, Query, Router, UploadedFile
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.core.utils import broadcast_to_workspace, verify_item_access
from sbomify.apps.sboms.models import Component
from sbomify.apps.sboms.utils import verify_download_token

from .models import Document
from .schemas import DocumentResponseSchema, DocumentUpdateRequest, DocumentUploadRequest
from .services.documents import delete_document_record, get_document_detail, update_document_metadata

log = logging.getLogger(__name__)

router = Router(tags=["Artifacts"], auth=(PersonalAccessTokenAuth(), django_auth))


@router.post(
    "/",
    response={201: DocumentUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def create_document(
    request: HttpRequest,
    component_id: str = None,
    document_file: UploadedFile = File(None),
    name: str = None,
    version: str = "1.0",
    document_type: str = "",
    description: str = "",
):
    """Create a new document for a component. Can handle both file uploads and raw data."""
    try:
        # Extract component_id from various sources
        actual_component_id = None

        if document_file:
            # File upload scenario - extract form data from request.POST
            form_component_id = request.POST.get("component_id")
            actual_component_id = form_component_id or component_id

            if not actual_component_id:
                return 400, {"detail": "component_id is required"}

            content = document_file.read()
            file_name = document_file.name
            content_type = (
                document_file.content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            )
            file_size = document_file.size
            source = "manual_upload"

            # Extract other parameters from form data
            form_name = request.POST.get("name")
            form_version = request.POST.get("version", "1.0")
            form_document_type = request.POST.get("document_type", "")
            form_description = request.POST.get("description", "")

            # Extract subcategory dynamically based on document type
            # Check for known subcategory fields
            compliance_subcategory = request.POST.get("compliance_subcategory", "") or None
            # Determine which subcategory to use based on document type
            subcategory_value = None
            if form_document_type == Document.DocumentType.COMPLIANCE and compliance_subcategory:
                subcategory_value = compliance_subcategory

            # Remove file extension if name not provided
            document_name = form_name or name or file_name.rsplit(".", 1)[0]
            version = form_version
            document_type = form_document_type
            description = form_description

            # Validate file size (max 50MB for documents)
            max_size = 50 * 1024 * 1024  # 50MB
            if file_size > max_size:
                return 400, {"detail": "File size must be less than 50MB"}
        else:
            # Raw data scenario (API upload) - use query parameters
            actual_component_id = request.GET.get("component_id") or component_id

            if not actual_component_id:
                return 400, {"detail": "component_id is required"}
            if not name:
                return 400, {"detail": "Name is required for raw data uploads"}

            content = request.body
            file_name = None
            content_type = request.content_type or "application/octet-stream"
            file_size = len(content)
            source = "api"
            document_name = name

        # Get the component
        component = Component.objects.filter(
            id=actual_component_id, component_type=Component.ComponentType.DOCUMENT
        ).first()
        if component is None:
            return 404, {"detail": "Document component not found"}

        if not verify_item_access(request, component, ["owner", "admin"]):
            return 403, {"detail": "Forbidden"}

        # Compute SHA256 hash of the document content
        sha256_hash = hashlib.sha256(content).hexdigest()

        # Upload to S3 using dedicated DOCUMENTS bucket (fallback to SBOMS if not configured)
        s3 = S3Client("DOCUMENTS")
        filename = s3.upload_document(content)

        document_dict = {
            "name": document_name,
            "version": version,
            "document_filename": filename,
            "component": component,
            "source": source,
            "content_type": content_type,
            "file_size": file_size,
            "document_type": document_type,
            "description": description,
            "sha256_hash": sha256_hash,
            "content_hash": sha256_hash,
        }

        # Add subcategory based on document type
        if document_type == Document.DocumentType.COMPLIANCE and subcategory_value:
            document_dict["compliance_subcategory"] = subcategory_value

        with transaction.atomic():
            document = Document(**document_dict)
            document.save()

        # Broadcast to workspace for real-time UI updates
        broadcast_to_workspace(
            workspace_key=component.team.key,
            message_type="document_uploaded",
            data={"document_id": str(document.id), "component_id": str(component.id), "name": document.name},
        )

        return 201, {"id": document.id}

    except Exception as e:
        log.error(f"Error creating document: {e}")
        return 400, {"detail": "Invalid request"}


@router.patch(
    "/{document_id}",
    response={200: DocumentResponseSchema, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def update_document(request: HttpRequest, document_id: str, payload: DocumentUpdateRequest):
    """Update document metadata."""
    result = update_document_metadata(request, document_id, payload)
    if not result.ok:
        return result.status_code or 400, {"detail": result.error or "Invalid request"}

    return 200, result.value


@router.get(
    "/{document_id}",
    response={200: DocumentResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
)
def get_document(request: HttpRequest, document_id: str):
    """Get a specific document by ID."""
    result = get_document_detail(request, document_id)
    if not result.ok:
        return result.status_code or 400, {"detail": result.error or "Invalid request"}

    return 200, result.value


@router.get(
    "/{document_id}/download",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
    auth=None,  # Allow unauthenticated access for public documents
)
def download_document(request: HttpRequest, document_id: str):
    """Download a document file.

    This endpoint allows direct download of document files. For public documents,
    no authentication is required. For private documents, user authentication
    and appropriate permissions are required.

    For private documents in product/project SBOMs, signed URLs are used instead
    to provide secure, time-limited access without requiring authentication.
    See the `/download/signed` endpoint for signed URL downloads.
    """
    try:
        document = Document.objects.select_related("component").get(pk=document_id)
    except Document.DoesNotExist:
        return 404, {"detail": "Document not found"}

    # Check access permissions using centralized access control
    from sbomify.apps.core.services.access_control import check_component_access

    component = document.component
    access_result = check_component_access(request, component)

    if access_result.has_access:
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
                return 404, {"detail": "Document file not found"}

        except Exception as e:
            log.error(f"Error retrieving document {document_id}: {e}")
            return 500, {"detail": "Error retrieving document"}
    else:
        # Provide helpful error message based on access result
        if access_result.requires_access_request:
            if not request.user.is_authenticated:
                return 403, {
                    "detail": "Access denied. Please request access to download this document.",
                    "requires_access_request": True,
                }
            else:
                return 403, {
                    "detail": "Access denied. Your access request is pending approval or has been rejected.",
                    "requires_access_request": True,
                }
        return 403, {"detail": "Access denied"}


@router.get(
    "/{document_id}/download/signed",
    response={200: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
    auth=None,  # No authentication required - token provides authorization
)
def download_document_signed(request: HttpRequest, document_id: str, token: str = Query(...)):
    """Download a document file using a signed token.

    This endpoint allows secure, time-limited access to private documents without
    requiring user authentication. It's primarily used when private documents are
    included in product/project SBOMs as external references.

    **Security Features:**
    - Tokens expire after 7 days
    - Tokens are tied to specific documents and users
    - Installation-specific signing prevents cross-site token reuse
    - Tamper-proof - any modification invalidates the token

    **Parameters:**
    - `document_id`: The ID of the document to download
    - `token`: A signed token generated by the system for authorized access

    **Token Generation:**
    Tokens are automatically generated when creating product/project SBOMs that
    contain private documents. They are embedded in the SBOM as external reference URLs.

    **Error Responses:**
    - 403: Invalid, expired, or mismatched token
    - 404: Document not found
    - 500: Server error retrieving document
    """
    try:
        document = Document.objects.select_related("component").get(pk=document_id)
    except Document.DoesNotExist:
        return 404, {"detail": "Document not found"}

    # Verify the signed token
    payload = verify_download_token(token)
    if not payload:
        return 403, {"detail": "Invalid or expired download token"}

    # Verify the token is for this specific document
    if payload.get("document_id") != document_id:
        return 403, {"detail": "Token is not valid for this document"}

    # For private components, we need to ensure the token is valid
    # The token itself provides the authorization
    from sbomify.apps.sboms.models import Component

    if document.component.visibility != Component.Visibility.PUBLIC:
        # Additional security: verify the user from the token exists
        user_id = payload.get("user_id")
        if not user_id:
            return 403, {"detail": "Invalid token: missing user information"}

        try:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            User.objects.get(id=user_id)
        except User.DoesNotExist:
            return 403, {"detail": "Invalid token: user not found"}

        # Log the access for audit purposes
        log.info(f"Signed URL access to private document {document_id} by user {user_id}")

    # Check if document file exists
    if not document.document_filename:
        return 404, {"detail": "Document file not found"}

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
            return 404, {"detail": "Document file not found"}

    except Exception as e:
        log.error(f"Error retrieving document {document_id} via signed URL: {e}")
        return 500, {"detail": "Error retrieving document"}


@router.delete(
    "/{document_id}",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
)
def delete_document(request: HttpRequest, document_id: str):
    """Delete a document."""
    result = delete_document_record(request, document_id)
    if not result.ok:
        return result.status_code or 400, {"detail": result.error or "Invalid request"}

    return 204, None
