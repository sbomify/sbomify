import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.forms import TeamGeneralSettingsForm
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.utils import (
    refresh_current_team_session,
    switch_active_workspace,
    update_user_teams_session,
)

logger = logging.getLogger(__name__)


class TeamGeneralView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """View for managing workspace general settings (name, default, deletion)."""

    allowed_roles = ["owner"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        form = TeamGeneralSettingsForm(initial={"name": team.name})

        membership = Member.objects.filter(user=request.user, team__key=team_key).first()
        is_default_team = membership.is_default_team if membership else False

        return render(
            request,
            "teams/team_general.html.j2",
            {
                "team": team,
                "form": form,
                "is_default_team": is_default_team,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        action = request.POST.get("action", "update_name")

        if action == "set_default":
            return self._set_default(request, team_key)
        elif action == "delete_workspace" or action == "delete":
            return self._delete_workspace(request, team_key)

        return self._update_name(request, team_key)

    def _update_name(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Update the workspace name."""
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        form = TeamGeneralSettingsForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        new_name = form.cleaned_data["name"]

        try:
            with transaction.atomic():
                team_obj = Team.objects.select_for_update().get(key=team_key)
                team_obj.name = new_name
                team_obj.save(update_fields=["name"])

            refresh_current_team_session(request, team_obj)

            return htmx_success_response(
                "Workspace settings updated successfully", triggers={"refreshTeamGeneral": True}
            )

        except Team.DoesNotExist:
            return htmx_error_response("Workspace not found")
        except Exception:
            logger.exception("Failed to update workspace name for team_key=%s", team_key)
            return htmx_error_response("Failed to update workspace. Please try again.")

    def _set_default(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Set this workspace as the default."""
        try:
            membership = Member.objects.select_related("team").get(user=request.user, team__key=team_key)

            with transaction.atomic():
                Member.objects.filter(user=request.user).update(is_default_team=False)
                membership.is_default_team = True
                membership.save(update_fields=["is_default_team"])

            update_user_teams_session(request, request.user)

            return htmx_success_response(
                f"{membership.team.name} is now your default workspace",
                triggers={"refreshTeamGeneral": True},
            )

        except Member.DoesNotExist:
            return htmx_error_response("Membership not found")
        except Exception:
            logger.exception("Failed to set default workspace for team_key=%s", team_key)
            return htmx_error_response("Failed to set default workspace. Please try again.")

    def _delete_workspace(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Delete the workspace."""
        try:
            membership = Member.objects.select_related("team").get(user=request.user, team__key=team_key, role="owner")

            if membership.is_default_team:
                return htmx_error_response(
                    "Cannot delete the default workspace. Please set another workspace as default first."
                )

            team = membership.team
            team_name = team.name

            with transaction.atomic():
                team.delete()

            # Update user teams session after deletion
            user_teams = update_user_teams_session(request, request.user)

            # Switch to default workspace, or first available if no default
            if user_teams:
                # Find default workspace, or use first available
                default_team_key = next((key for key, data in user_teams.items() if data.get("is_default_team")), None)

                target_team_key = default_team_key or next(iter(user_teams.keys()))

                try:
                    # Get the team object and switch to it using the proper function
                    target_team = Team.objects.get(key=target_team_key)
                    switch_active_workspace(request, target_team)

                    logger.info(
                        "Switched to %s workspace %s after deleting %s",
                        "default" if default_team_key else "first available",
                        target_team_key,
                        team_key,
                    )
                except Team.DoesNotExist:
                    logger.error("Target workspace %s not found after deletion", target_team_key)
                    # Fallback: manually set session
                    target_team_data = user_teams[target_team_key]
                    request.session["current_team"] = {"key": target_team_key, **target_team_data}
                    request.session.modified = True
                    request.session.save()
                except Exception as e:
                    logger.error("Error switching workspace after deletion: %s", e, exc_info=True)
                    # Fallback: manually set session
                    target_team_data = user_teams[target_team_key]
                    request.session["current_team"] = {"key": target_team_key, **target_team_data}
                    request.session.modified = True
                    request.session.save()
            else:
                # No workspaces left - this shouldn't happen if validation is correct
                logger.warning("User %s has no workspaces after deleting %s", request.user.id, team_key)
                request.session.pop("current_team", None)
                request.session.modified = True
                request.session.save()

            messages.success(request, f"Workspace {team_name} has been deleted")

            # Use regular Django redirect to ensure session is saved
            return redirect("core:dashboard")

        except Member.DoesNotExist:
            return htmx_error_response("You don't have permission to delete this workspace")
        except Exception:
            logger.exception("Failed to delete workspace for team_key=%s", team_key)
            return htmx_error_response("Failed to delete workspace. Please try again.")
