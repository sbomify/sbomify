from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.documents.services.documents_table import (
    build_documents_table_context,
    delete_document_from_request,
    update_document_from_request,
)


class DocumentsTableView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, component_id: str, is_public_view: bool) -> HttpResponse:
        result = build_documents_table_context(request, component_id, is_public_view)
        if not result.ok:
            return htmx_error_response(result.error or "Unknown error")

        return render(request, "documents/documents_table.html.j2", result.value)

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.POST.get("_method") == "DELETE":
            return self._delete(request)
        elif request.POST.get("_method") == "PATCH":
            return self._patch(request)

        return htmx_error_response("Invalid request")

    def _delete(self, request: HttpRequest) -> HttpResponse:
        result = delete_document_from_request(request)
        if not result.ok:
            return htmx_error_response(result.error or "Failed to delete document")

        return htmx_success_response("Document deleted successfully", triggers={"refreshDocumentsTable": True})

    def _patch(self, request: HttpRequest) -> HttpResponse:
        result = update_document_from_request(request)
        if not result.ok:
            return htmx_error_response(result.error or "Failed to update document")

        return htmx_success_response("Document updated successfully", triggers={"refreshDocumentsTable": True})
