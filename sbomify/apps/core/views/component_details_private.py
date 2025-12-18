from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response


class ComponentDetailsPrivateView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            from sbomify.apps.core.views.component_details_public import ComponentDetailsPublicView

            return ComponentDetailsPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team", {})
        is_owner = current_team.get("role") == "owner"
        billing_plan = current_team.get("billing_plan")

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "component": component,
            "current_team": current_team,
            "is_owner": is_owner,
            "team_billing_plan": billing_plan,
        }

        component_type = component.get("component_type")
        if component_type == "sbom":
            template_name = "core/component_details_private_sbom.html.j2"
        elif component_type == "document":
            template_name = "core/component_details_private_document.html.j2"
        else:
            template_name = "core/component_details_private.html.j2"

        return render(request, template_name, context)
