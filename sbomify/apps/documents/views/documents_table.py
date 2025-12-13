from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component, list_component_documents
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.documents.apis import delete_document, update_document
from sbomify.apps.documents.forms import DocumentDeleteForm, DocumentEditForm
from sbomify.apps.documents.models import Document
from sbomify.apps.documents.schemas import DocumentUpdateRequest


class DocumentsTableView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, component_id: str, is_public_view: bool) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return htmx_error_response(component.get("detail", "Unknown error"))

        status_code, documents = list_component_documents(request, component_id, page=1, page_size=-1)
        if status_code != 200:
            return htmx_error_response(documents.get("detail", "Failed to load documents"))

        context = {
            "component_id": component_id,
            "documents": documents.get("items"),
            "is_public_view": is_public_view,
            "has_crud_permissions": component.get("has_crud_permissions") if not is_public_view else False,
            "delete_form": DocumentDeleteForm(),
            "document_type_choices": Document.DocumentType.choices,
        }

        return render(request, "documents/documents_table.html.j2", context)

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.POST.get("_method") == "DELETE":
            return self._delete(request)
        elif request.POST.get("_method") == "PATCH":
            return self._patch(request)

        return htmx_error_response("Invalid request")

    def _delete(self, request: HttpRequest) -> HttpResponse:
        form = DocumentDeleteForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        document_id = form.cleaned_data["document_id"]

        status_code, result = delete_document(request, document_id)
        if status_code != 204:
            return htmx_error_response(result.get("detail", "Failed to delete document"))

        return htmx_success_response("Document deleted successfully", triggers={"refreshDocumentsTable": True})

    def _patch(self, request: HttpRequest) -> HttpResponse:
        form = DocumentEditForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        document_id = form.cleaned_data["document_id"]
        payload = DocumentUpdateRequest(
            name=form.cleaned_data.get("name"),
            version=form.cleaned_data.get("version"),
            document_type=form.cleaned_data.get("document_type"),
            description=form.cleaned_data.get("description"),
        )

        status_code, result = update_document(request, document_id, payload)
        if status_code != 200:
            return htmx_error_response(result.get("detail", "Failed to update document"))

        return htmx_success_response("Document updated successfully", triggers={"refreshDocumentsTable": True})
