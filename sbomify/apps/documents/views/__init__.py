import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_public_path,
    get_workspace_public_url,
    resolve_document_identifier,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.documents.models import Document
from sbomify.apps.documents.views.documents_table import DocumentsTableView  # noqa: F401
from sbomify.apps.teams.branding import build_branding_context

logger = logging.getLogger(__name__)


class DocumentDetailsPublicView(View):
    """Public document details view following the same pattern as other public views."""

    def get(self, request: HttpRequest, document_id: str) -> HttpResponse:
        # Resolve document by slug (on custom domains) or ID (on main app)
        document_obj = resolve_document_identifier(request, document_id)
        if not document_obj:
            return error_response(request, HttpResponseNotFound("Document not found"))

        # Ensure we have the related component and team loaded
        if not hasattr(document_obj, "component") or document_obj.component is None:
            document_obj = Document.objects.select_related("component__team").get(pk=document_obj.id)

        team = getattr(document_obj.component, "team", None)

        if not document_obj.public_access_allowed:
            return error_response(request, HttpResponseForbidden("Document is not public"))

        # Redirect to custom domain if team has a verified one and we're not already on it
        # OR redirect from /public/ URL to clean URL on custom domain
        if team and (should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request)):
            path = get_public_path("document", document_obj.id, is_custom_domain=True, slug=document_obj.name)
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))

        brand = build_branding_context(team)

        # Generate workspace URL based on context
        workspace_public_url = get_workspace_public_url(request, team)

        context = {
            "document": document_obj,
            "brand": brand,
            "APP_BASE_URL": settings.APP_BASE_URL,
            "workspace_public_url": workspace_public_url,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "documents/document_details_public.html.j2", context)


class DocumentDetailsPrivateView(LoginRequiredMixin, View):
    """Private document details view - delegates to public view on custom domains."""

    def dispatch(self, request, *args, **kwargs):
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            return DocumentDetailsPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, document_id: str) -> HttpResponse:
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


# Keep function aliases for URL routing compatibility
def document_details_private(request: HttpRequest, document_id: str) -> HttpResponse:
    return DocumentDetailsPrivateView.as_view()(request, document_id=document_id)


def document_details_public(request: HttpRequest, document_id: str) -> HttpResponse:
    return DocumentDetailsPublicView.as_view()(request, document_id=document_id)


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
