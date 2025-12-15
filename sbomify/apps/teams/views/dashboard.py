from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.apis import list_teams
from sbomify.apps.teams.forms import AddTeamForm, DeleteTeamForm, UpdateTeamForm
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.utils import update_user_teams_session


class WorkspacesDashboardView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        status_code, teams = list_teams(request)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=teams.get("detail", "Unknown error"))
            )

        update_user_teams_session(request, request.user)

        return render(
            request,
            "teams/dashboard.html.j2",
            {
                "add_form": AddTeamForm(),
                "delete_form": DeleteTeamForm(),
                "update_form": UpdateTeamForm(),
                "teams": teams,
            },
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        if request.POST.get("_method") == "POST":
            return self._post(request)
        elif request.POST.get("_method") == "PATCH":
            return self._patch(request)
        elif request.POST.get("_method") == "DELETE":
            return self._delete(request)

        messages.error(request, "Invalid request method")
        return redirect("teams:teams_dashboard")

    def _post(self, request: HttpRequest) -> HttpResponse:
        form = AddTeamForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return redirect("teams:teams_dashboard")

        form.save(user=request.user)
        update_user_teams_session(request, request.user)
        messages.add_message(
            request,
            messages.SUCCESS,
            f"Workspace {form.instance.name} created successfully",
        )

        return redirect("teams:switch_team", team_key=form.instance.key)

    def _patch(self, request: HttpRequest) -> HttpResponse:
        form = UpdateTeamForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return redirect("teams:teams_dashboard")

        try:
            team = Team.objects.get(key=form.cleaned_data["key"])
            membership = Member.objects.get(user=request.user, team=team)

            with transaction.atomic():
                Member.objects.filter(user=request.user).update(is_default_team=False)
                membership.is_default_team = True
                membership.save()

            messages.add_message(
                request,
                messages.INFO,
                f"Workspace {team.name} updated successfully",
            )
            update_user_teams_session(request, request.user)

        except Member.DoesNotExist:
            messages.error(request, "Membership not found")
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")

        return redirect("teams:teams_dashboard")

    def _delete(self, request: HttpRequest) -> HttpResponse:
        form = DeleteTeamForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return redirect("teams:teams_dashboard")

        try:
            team = Team.objects.get(key=form.cleaned_data["key"])
            # TODO move it to permissions
            membership = Member.objects.get(user=request.user, team=team, role="owner")

            if membership.is_default_team:
                messages.add_message(
                    request,
                    messages.ERROR,
                    "Cannot delete the default workspace. Please set another workspace as default first.",
                )
            else:
                with transaction.atomic():
                    team.delete()

                messages.add_message(
                    request,
                    messages.INFO,
                    f"Workspace {team.name} has been deleted",
                )
                update_user_teams_session(request, request.user)
        except Member.DoesNotExist:
            messages.error(request, "Membership not found")
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")

        return redirect("teams:teams_dashboard")
