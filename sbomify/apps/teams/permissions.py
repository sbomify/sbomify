from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.models import Member


class TeamRoleRequiredMixin(AccessMixin):
    allowed_roles: list[str] = []

    def dispatch(self, request, *args, **kwargs):
        current_team = request.session.get("current_team", {})

        team_key = current_team.get("key", None)
        if team_key is None:
            return error_response(request, HttpResponseForbidden("You are not a member of any team"))

        try:
            Member.objects.get(user=request.user, team__key=team_key, role__in=self.allowed_roles)
        except Member.DoesNotExist:
            # Check if user has ANY membership in this team (just not the right role)
            has_any_membership = Member.objects.filter(user=request.user, team__key=team_key).exists()

            if has_any_membership:
                # User is a member but doesn't have the required role
                return error_response(
                    request, HttpResponseForbidden("You don't have sufficient permissions to access this page")
                )

            # User is not a member of this workspace at all - they may have been removed
            # Try to switch to another workspace they are a member of
            return self._handle_stale_session(request)

        return super().dispatch(request, *args, **kwargs)

    def _handle_stale_session(self, request):
        """Handle case where user's session points to a workspace they're no longer a member of."""
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

        # Fallback if workspace creation failed
        request.session.pop("current_team", None)
        request.session.modified = True
        return error_response(request, HttpResponseForbidden("You are not a member of any team"))
