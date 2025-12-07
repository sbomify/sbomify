from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component, list_component_documents
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.documents.forms import DocumentDeleteForm, DocumentEditForm
from sbomify.apps.documents.models import Document


class DocumentsTableView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return htmx_error_response(component.get("detail", "Unknown error"))

        is_public_view = request.path.startswith("/public/")

        # Load all documents at once (client-side pagination)
        status_code, documents_response = list_component_documents(request, component_id, page=1, page_size=-1)
        if status_code != 200:
            return htmx_error_response(documents_response.get("detail", "Failed to load documents"))

        context = {
            "documents_data": documents_response.get("items", []),
            "is_public_view": is_public_view,
            "has_crud_permissions": component.get("has_crud_permissions", False) if not is_public_view else False,
            "document_type_choices": Document.DocumentType.choices,
            "component_id": component_id,
        }

        # Only add delete form for private views
        if not is_public_view:
            context["delete_form"] = DocumentDeleteForm()

        # Prepare data for Alpine.js component
        import json

        documents_table_data = {
            "componentId": component_id,
            "isPublicView": is_public_view,
            "hasCrudPermissions": component.get("has_crud_permissions", False) if not is_public_view else False,
            "documentsData": documents_response.get("items", []),
        }
        context["documents_table_data_json"] = json.dumps(documents_table_data)

        return render(request, "documents/documents_table.html.j2", context)

    def post(self, request: HttpRequest, component_id: str) -> HttpResponse:
        if request.POST.get("_method") == "DELETE":
            return self._delete(request, component_id)
        elif request.POST.get("_method") == "PATCH":
            return self._patch(request, component_id)

        return htmx_error_response("Invalid request")

    def _delete(self, request: HttpRequest, component_id: str) -> HttpResponse:
        form = DocumentDeleteForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        document_id = form.cleaned_data["document_id"]

        try:
            document = Document.objects.select_related("component").get(pk=document_id)
        except Document.DoesNotExist:
            return htmx_error_response("Document not found")

        if not verify_item_access(request, document.component, ["owner", "admin"]):
            return htmx_error_response("Only owners and admins can delete documents")

        document_name = document.name
        document.delete()

        messages.success(request, f"Document '{document_name}' deleted successfully")
        return htmx_success_response(
            f"Document '{document_name}' deleted successfully", triggers={"refreshDocumentsTable": True}
        )

    def _patch(self, request: HttpRequest, component_id: str) -> HttpResponse:
        """Handle document update."""
        form = DocumentEditForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        document_id = form.cleaned_data["document_id"]

        try:
            document = Document.objects.select_related("component").get(pk=document_id)
        except Document.DoesNotExist:
            return htmx_error_response("Document not found")

        if not verify_item_access(request, document.component, ["owner", "admin"]):
            return htmx_error_response("Only owners and admins can update documents")

        # Update document
        if form.cleaned_data.get("name"):
            document.name = form.cleaned_data["name"]
        if form.cleaned_data.get("version"):
            document.version = form.cleaned_data["version"]
        if form.cleaned_data.get("document_type") is not None:
            document.document_type = form.cleaned_data["document_type"]
        if form.cleaned_data.get("description") is not None:
            document.description = form.cleaned_data["description"]

        document.save()

        return htmx_success_response("Document updated successfully", triggers={"refreshDocumentsTable": True})
