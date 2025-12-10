from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.apis import get_component, list_component_documents, list_component_sboms
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ComponentDetailsPublicView(View):
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

        team = Team.objects.filter(pk=component.get("team_id")).first()

        # Don't redirect - always show public content on whichever domain the user is on
        # Public pages should be accessible on both main domain and custom domain

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

        brand = build_branding_context(team)

        # Generate workspace URL based on context
        workspace_public_url = ""
        if team:
            if is_custom_domain:
                workspace_public_url = "/"
            elif team.key:
                workspace_public_url = reverse("core:workspace_public", kwargs={"workspace_key": team.key})

        current_team = request.session.get("current_team") or {}
        team_billing_plan = getattr(team, "billing_plan", None) or current_team.get("billing_plan")

        return render(
            request,
            "core/component_details_public.html.j2",
            {
                **context,
                "brand": brand,
                "team_billing_plan": team_billing_plan,
                "workspace_public_url": workspace_public_url,
                "is_custom_domain": is_custom_domain,
                "custom_domain": team.custom_domain if is_custom_domain else None,
            },
        )
