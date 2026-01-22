from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import (
    HttpRequest,
    HttpResponse,
)
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.apis import create_component, list_components
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.schemas import ComponentCreateSchema


def _get_components_context(request: HttpRequest) -> dict | None:
    """Helper to get common context for components views."""
    status_code, components = list_components(request, page=1, page_size=-1)
    if status_code != 200:
        return None

    current_team = request.session.get("current_team")
    has_crud_permissions = current_team.get("role") in ["owner", "admin"]

    # Sort components alphabetically by name
    sorted_components = sorted(components.items, key=lambda c: c.name.lower())

    return {
        "current_team": current_team,
        "has_crud_permissions": has_crud_permissions,
        "components": sorted_components,
    }


class ComponentsDashboardView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        context = _get_components_context(request)
        if context is None:
            return error_response(request, HttpResponse(status=500, content="Failed to load components"))

        return render(request, "core/components_dashboard.html.j2", context)

    def post(self, request: HttpRequest) -> HttpResponse:
        name = request.POST.get("name", "").strip()
        component_type = request.POST.get("component_type", "sbom")
        is_global = request.POST.get("is_global") == "on"

        payload = ComponentCreateSchema(
            name=name,
            component_type=component_type,
            metadata={},
            is_global=is_global,
        )

        status_code, response = create_component(request, payload)
        if status_code == 201:
            messages.success(request, f'Component "{name}" created successfully!')
        else:
            error_detail = response.get("detail", "An error occurred while creating the component")
            messages.error(request, error_detail)

        return redirect("core:components_dashboard")


class ComponentsTableView(LoginRequiredMixin, View):
    """View for HTMX table refresh."""

    def get(self, request: HttpRequest) -> HttpResponse:
        context = _get_components_context(request)
        if context is None:
            return error_response(request, HttpResponse(status=500, content="Failed to load components"))

        return render(request, "core/components_table.html.j2", context)
