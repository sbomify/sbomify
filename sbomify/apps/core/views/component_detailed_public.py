from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.core.url_utils import add_custom_domain_to_context, resolve_component_identifier
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.branding import build_branding_context


class ComponentDetailedPublicView(View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        # Resolve component by slug (on custom domains) or ID (on main app)
        component_obj = resolve_component_identifier(request, component_id)
        if not component_obj:
            return error_response(request, HttpResponseNotFound("Component not found"))

        # Use the resolved component's ID for API calls
        resolved_id = component_obj.id

        status_code, component = get_component(request, resolved_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        if component.get("component_type") == Component.ComponentType.SBOM:
            data = SBOM.objects.filter(component_id=resolved_id).order_by("-created_at").first()
            if not data:
                return error_response(request, HttpResponseNotFound("No SBOM found for this component"))

        elif component.get("component_type") == Component.ComponentType.DOCUMENT:
            data = Document.objects.filter(component_id=resolved_id).order_by("-created_at").first()
            if not data:
                return error_response(request, HttpResponseNotFound("No document found for this component"))

        else:
            return error_response(request, HttpResponseNotFound("Unknown component type"))

        component_obj = getattr(data, "component", None)
        team = getattr(component_obj, "team", None)

        brand = build_branding_context(team)

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "brand": brand,
            "component": component,
            "data": data,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/component_detailed_public.html.j2", context)
