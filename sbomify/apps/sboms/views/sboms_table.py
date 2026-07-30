from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.sboms.services.sboms_table import build_sboms_table_context, delete_sbom_from_request


class SbomsTableView(View):
    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """Gate the private route only, the way DocumentsTableView does.

        One class serves both routes. A public component clears the
        component-level check even for an anonymous caller, so without this the
        private route reached the workspace lookup holding AnonymousUser and
        raised. A blanket login requirement would wrongly close the public route.
        """
        if not kwargs.get("is_public_view", False) and not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            from django.urls import reverse

            return redirect_to_login(request.get_full_path(), reverse("core:keycloak_login"))

        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, component_id: str, is_public_view: bool) -> HttpResponse:
        result = build_sboms_table_context(request, component_id, is_public_view)
        if not result.ok:
            return htmx_error_response(result.error or "Unknown error")

        return render(request, "sboms/sboms_table.html.j2", result.value)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.POST.get("_method") == "DELETE":
            return self._delete(request)

        return htmx_error_response("Invalid request")

    def _delete(self, request: HttpRequest) -> HttpResponse:
        result = delete_sbom_from_request(request)
        if not result.ok:
            return htmx_error_response(result.error or "Failed to delete SBOM")

        return htmx_success_response("SBOM deleted successfully", triggers={"refreshSbomsTable": True})
