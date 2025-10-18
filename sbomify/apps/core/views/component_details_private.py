from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.core.utils import verify_item_access


class ComponentDetailsPrivateView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        from sbomify.apps.core.apis import list_component_documents, list_component_sboms

        try:
            component: Component = Component.objects.get(pk=component_id)
        except Component.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Component not found"))

        # Verify access to project
        if not verify_item_access(request, component, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

        has_crud_permissions = verify_item_access(request, component, ["owner", "admin"])
        is_owner = verify_item_access(request, component, ["owner"])

        context = {
            "component": component,
            "has_crud_permissions": has_crud_permissions,
            "is_owner": is_owner,
            "APP_BASE_URL": settings.APP_BASE_URL,
            "current_team": request.session.get("current_team", {}),
            "team_billing_plan": getattr(component.team, "billing_plan", "community"),
        }

        if component.component_type == Component.ComponentType.SBOM:
            status_code, sboms_response = list_component_sboms(request, component_id, page=1, page_size=-1)
            context["sboms_data"] = sboms_response.get("items", []) if status_code == 200 else []

        elif component.component_type == Component.ComponentType.DOCUMENT:
            status_code, documents_response = list_component_documents(request, component_id, page=1, page_size=-1)
            context["documents_data"] = documents_response.get("items", []) if status_code == 200 else []

        return render(request, "core/component_details_private.html.j2", context)
