from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM


class ComponentDetailedPrivateView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
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

        current_team = request.session.get("current_team", {})

        return render(
            request,
            "core/component_detailed_private.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "component": component,
                "current_team": current_team,
                "data": data,
            },
        )
