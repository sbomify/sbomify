from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.sboms.services.sboms_table import build_sboms_table_context, delete_sbom_from_request


class SbomsTableView(View):
    def get(self, request: HttpRequest, component_id: str, is_public_view: bool) -> HttpResponse:
        result = build_sboms_table_context(request, component_id, is_public_view)
        if not result.ok:
            return htmx_error_response(result.error or "Unknown error")

        return render(request, "sboms/sboms_table.html.j2", result.value)

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.POST.get("_method") == "DELETE":
            return self._delete(request)

        return htmx_error_response("Invalid request")

    def _delete(self, request: HttpRequest) -> HttpResponse:
        result = delete_sbom_from_request(request)
        if not result.ok:
            return htmx_error_response(result.error or "Failed to delete SBOM")

        return htmx_success_response("SBOM deleted successfully", triggers={"refreshSbomsTable": True})
