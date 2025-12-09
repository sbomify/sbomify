from django.contrib import messages
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
                return self._recover_workspace_session(request)

        return super().dispatch(request, *args, **kwargs)

    def _recover_workspace_session(self, request):
        """Recover session when user was removed from their current workspace."""
        from sbomify.apps.teams.utils import create_user_team_and_subscription, get_user_teams

        # Get the name of the old workspace before we update the session
        current_team = request.session.get("current_team", {})
        old_team_name = current_team.get("name", "the workspace")

        # Refresh user teams from database
        user_teams = get_user_teams(request.user)
        request.session["user_teams"] = user_teams

        if user_teams:
            # User has other workspaces, switch to the first one
            next_team_key, next_team = next(iter(user_teams.items()))
            request.session["current_team"] = {"key": next_team_key, **next_team}
            request.session.modified = True
            messages.warning(
                request, f"You have been removed from {old_team_name}. You have been switched to your other workspace."
            )
            return redirect("core:dashboard")

        # User has no workspaces at all - create a personal workspace for them
        new_team = create_user_team_and_subscription(request.user)
        if new_team:
            user_teams = get_user_teams(request.user)
            request.session["user_teams"] = user_teams
            request.session["current_team"] = {"key": new_team.key, **user_teams.get(new_team.key, {})}
            request.session.modified = True
            messages.warning(
                request,
                f"You have been removed from {old_team_name}. You have been switched to your new personal workspace.",
            )
            return redirect("core:dashboard")

        # Fallback
        request.session.pop("current_team", None)
        request.session.modified = True
        messages.error(request, "Unable to find or create a workspace for you.")
        return redirect("core:dashboard")


class DashboardView(ValidateWorkspaceMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
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

        current_team = request.session.get("current_team", {})

        context = {
            "current_team": current_team,
            "data": {
                "products": len(products.items),
                "projects": len(projects.items),
                "components": len(components.items),
            },
        }

        return render(request, "core/dashboard.html.j2", context)
