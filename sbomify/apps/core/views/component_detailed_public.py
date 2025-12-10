from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.branding import build_branding_context


class ComponentDetailedPublicView(View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        # Check if this is a custom domain request
        is_custom_domain = getattr(request, "is_custom_domain", False)

        # If on custom domain, verify the component belongs to this workspace
        if is_custom_domain and hasattr(request, "custom_domain_team"):
            try:
                component_obj = Component.objects.get(id=component_id)
                if component_obj.team != request.custom_domain_team:
                    return error_response(request, HttpResponseNotFound("Component not found"))
            except Component.DoesNotExist:
                return error_response(request, HttpResponseNotFound("Component not found"))

        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        if component.get("component_type") == Component.ComponentType.SBOM:
            data = SBOM.objects.filter(component_id=component_id).order_by("-created_at").first()
            if not data:
                return error_response(request, HttpResponseNotFound("No SBOM found for this component"))

        elif component.get("component_type") == Component.ComponentType.DOCUMENT:
            data = Document.objects.filter(component_id=component_id).order_by("-created_at").first()
            if not data:
                return error_response(request, HttpResponseNotFound("No document found for this component"))

        else:
            return error_response(request, HttpResponseNotFound("Unknown component type"))

        component_obj = getattr(data, "component", None)
        team = getattr(component_obj, "team", None)

        # Don't redirect - always show public content on whichever domain the user is on
        # Public pages should be accessible on both main domain and custom domain

        brand = build_branding_context(team)

        return render(
            request,
            "core/component_detailed_public.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "brand": brand,
                "component": component,
                "data": data,
                "is_custom_domain": is_custom_domain,
                "custom_domain": team.custom_domain if is_custom_domain and team else None,
            },
        )
