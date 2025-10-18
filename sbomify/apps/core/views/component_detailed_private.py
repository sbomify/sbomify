from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.core.utils import verify_item_access


class ComponentDetailedPrivateView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        try:
            component: Component = Component.objects.get(pk=component_id)
        except Component.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Component not found"))

        if not verify_item_access(request, component, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

        has_crud_permissions = verify_item_access(request, component, ["owner", "admin"])

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
            "core/component_detailed_private.html.j2",
            {
                "component": component,
                "has_crud_permissions": has_crud_permissions,
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": request.session.get("current_team", {}),
                "data": data,
            },
        )
