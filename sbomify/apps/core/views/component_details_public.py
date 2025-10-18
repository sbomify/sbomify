from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.teams.schemas import BrandingInfo


class ComponentDetailsPublicView(View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        from sbomify.apps.core.apis import list_component_documents, list_component_sboms

        try:
            component: Component = Component.objects.get(pk=component_id)
        except Component.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Component not found"))

        if not component.is_public:
            return error_response(request, HttpResponseForbidden("Component is not public"))

        context = {
            "component": component,
            "brand": BrandingInfo(**component.team.branding_info),
            "APP_BASE_URL": settings.APP_BASE_URL,
            "team_billing_plan": getattr(component.team, "billing_plan", "community"),
        }

        if component.component_type == Component.ComponentType.SBOM:
            status_code, sboms_response = list_component_sboms(request, component_id, page=1, page_size=-1)
            context["sboms_data"] = sboms_response.get("items", []) if status_code == 200 else []

        elif component.component_type == Component.ComponentType.DOCUMENT:
            status_code, documents_response = list_component_documents(request, component_id, page=1, page_size=-1)
            context["documents_data"] = documents_response.get("items", []) if status_code == 200 else []

        else:
            return error_response(request, HttpResponseNotFound("Component type not found"))

        return render(request, "core/component_details_public.html.j2", context)
