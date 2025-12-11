from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.apis import get_component, list_component_documents, list_component_sboms
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.core.url_utils import (
    add_custom_domain_to_context,
    build_custom_domain_url,
    get_public_path,
    resolve_component_identifier,
    should_redirect_to_custom_domain,
)
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ComponentDetailsPublicView(View):
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

        team = Team.objects.filter(pk=component.get("team_id")).first()

        # Redirect to custom domain if team has a verified one and we're not already on it
        if team and should_redirect_to_custom_domain(request, team):
            path = get_public_path("component", resolved_id, is_custom_domain=True, slug=component_obj.slug)
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))

        is_custom_domain = getattr(request, "is_custom_domain", False)

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "component": component,
        }

        if component.get("component_type") == Component.ComponentType.SBOM:
            status_code, sboms_response = list_component_sboms(request, resolved_id, page=1, page_size=-1)
            if status_code != 200:
                return error_response(
                    request, HttpResponse(status=status_code, content=sboms_response.get("detail", "Unknown error"))
                )
            context["sboms_data"] = sboms_response.get("items", [])

        elif component.get("component_type") == Component.ComponentType.DOCUMENT:
            status_code, documents_response = list_component_documents(request, resolved_id, page=1, page_size=-1)
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

        context.update(
            {
                "brand": brand,
                "team_billing_plan": team_billing_plan,
                "workspace_public_url": workspace_public_url,
            }
        )
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/component_details_public.html.j2", context)
