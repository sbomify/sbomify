from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.apis import list_components, list_products, list_projects
from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.models import Member


class ValidateWorkspaceMixin:
    """Mixin that validates the user is still a member of their current workspace."""

    def dispatch(self, request, *args, **kwargs):
        current_team = request.session.get("current_team", {})
        team_key = current_team.get("key")

        if team_key:
            # Check if user is still a member of this workspace
            is_member = Member.objects.filter(user=request.user, team__key=team_key).exists()

            if not is_member:
                # User was removed from this workspace, recover their session
                from sbomify.apps.teams.utils import recover_workspace_session

                return recover_workspace_session(request)

        return super().dispatch(request, *args, **kwargs)


class DashboardView(ValidateWorkspaceMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team", {})

        # Redirect to onboarding wizard if user hasn't completed it yet
        if not current_team.get("has_completed_wizard", True):
            return redirect("teams:onboarding_wizard")

        status_code, products = list_products(request, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=products.get("detail", "Unknown error"))
            )

        status_code, projects = list_projects(request, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=projects.get("detail", "Unknown error"))
            )

        status_code, components = list_components(request, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=components.get("detail", "Unknown error"))
            )

        context = {
            "current_team": current_team,
            "data": {
                "products": len(products.items),
                "projects": len(projects.items),
                "components": len(components.items),
            },
        }

        return render(request, "core/dashboard.html.j2", context)
