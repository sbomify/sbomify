from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.teams.schemas import BrandingInfo


class ComponentDetailedPublicView(View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        try:
            component = Component.objects.get(pk=component_id)
        except Component.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Component not found"))

        if not component.is_public:
            return error_response(request, HttpResponseNotFound("Component not found"))

        branding_info = BrandingInfo(**component.team.branding_info)

        if component.component_type == Component.ComponentType.SBOM:
            from sbomify.apps.sboms.models import SBOM

            data = SBOM.objects.filter(component_id=component_id).order_by("-created_at").first()
            if not data:
                return error_response(request, HttpResponseNotFound("No SBOM found for this component"))

        elif component.component_type == Component.ComponentType.DOCUMENT:
            from sbomify.apps.documents.models import Document

            data = Document.objects.filter(component_id=component_id).order_by("-created_at").first()
            if not data:
                return error_response(request, HttpResponseNotFound("No document found for this component"))

        else:
            return error_response(request, HttpResponseNotFound("Unknown component type"))

        return render(
            request,
            "core/component_detailed_public.html.j2",
            {
                "component": component,
                "data": data,
                "brand": branding_info,
                "APP_BASE_URL": settings.APP_BASE_URL,
            },
        )
