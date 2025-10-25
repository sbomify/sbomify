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


class ComponentsDashboardView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        status_code, components = list_components(request, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=components.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team")
        has_crud_permissions = current_team.get("role") in ["owner", "admin"]

        return render(
            request,
            "core/components_dashboard.html.j2",
            {
                "current_team": current_team,
                "has_crud_permissions": has_crud_permissions,
                "components": components.items,
            },
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        name = request.POST.get("name", "").strip()
        component_type = request.POST.get("component_type", "sbom")

        payload = ComponentCreateSchema(
            name=name,
            component_type=component_type,
            metadata={},
        )

        status_code, response = create_component(request, payload)
        if status_code == 201:
            messages.success(request, f'Component "{name}" created successfully!')
        else:
            error_detail = response.get("detail", "An error occurred while creating the component")
            messages.error(request, error_detail)

        return redirect("core:components_dashboard")
