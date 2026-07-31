from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.sboms.services.vex_documents import build_component_vex_context, delete_vex_from_request


class ComponentVexDocumentsView(View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        result = build_component_vex_context(request, component_id)
        if not result.ok:
            return htmx_error_response(result.error or "Unknown error")

        return render(request, "sboms/vex_documents.html.j2", result.value)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.POST.get("_method") == "DELETE":
            result = delete_vex_from_request(request)
            if not result.ok:
                return htmx_error_response(result.error or "Failed to delete VEX document")
            return htmx_success_response("VEX document deleted", triggers={"refreshVexDocuments": True})

        return htmx_error_response("Invalid request")
