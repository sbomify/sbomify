from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component, list_component_documents, list_component_sboms
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ComponentDetailsPublicView(View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "component": component,
        }

        if component.get("component_type") == Component.ComponentType.SBOM:
            status_code, sboms_response = list_component_sboms(request, component_id, page=1, page_size=-1)
            if status_code != 200:
                return error_response(
                    request, HttpResponse(status=status_code, content=sboms_response.get("detail", "Unknown error"))
                )
            context["sboms_data"] = sboms_response.get("items", [])

        elif component.get("component_type") == Component.ComponentType.DOCUMENT:
            status_code, documents_response = list_component_documents(request, component_id, page=1, page_size=-1)
            if status_code != 200:
                return error_response(
                    request, HttpResponse(status=status_code, content=documents_response.get("detail", "Unknown error"))
                )
            context["documents_data"] = documents_response.get("items", [])

        else:
            return error_response(request, HttpResponseNotFound("Unknown component type"))

        team = Team.objects.filter(pk=component.get("team_id")).first()
        brand = build_branding_context(team)
        current_team = request.session.get("current_team") or {}
        team_billing_plan = getattr(team, "billing_plan", None) or current_team.get("billing_plan")

        return render(
            request,
            "core/component_details_public.html.j2",
            {**context, "brand": brand, "team_billing_plan": team_billing_plan},
        )
