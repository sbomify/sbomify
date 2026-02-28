from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.forms import CreateAccessTokenForm
from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin


class TeamTokensView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """View for managing personal access tokens in workspace settings."""

    allowed_roles = ["owner", "admin", "member"]

    def _get_team_tokens_context(self, team, request: HttpRequest, extra_context: dict = None) -> dict:
        team_id = token_to_number(team.key)

        # Show tokens scoped to this team + any unscoped legacy tokens
        scoped_tokens = AccessToken.objects.filter(user=request.user, team_id=team_id).order_by("-created_at")
        unscoped_tokens = AccessToken.objects.filter(user=request.user, team__isnull=True).order_by("-created_at")

        context = {
            "team": team,
            "create_access_token_form": CreateAccessTokenForm(),
            "access_tokens": scoped_tokens,
            "unscoped_tokens": unscoped_tokens,
            "has_unscoped_tokens": unscoped_tokens.exists(),
        }
        if extra_context:
            context.update(extra_context)
        return context

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        return render(
            request,
            "teams/team_tokens.html.j2",
            self._get_team_tokens_context(team, request),
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        form = CreateAccessTokenForm(request.POST)
        if not form.is_valid():
            first_error = next(iter(form.errors.values()))[0]
            return htmx_error_response(first_error)

        team_id = token_to_number(team_key)

        access_token_str = create_personal_access_token(request.user)
        token = AccessToken(
            encoded_token=access_token_str,
            user=request.user,
            description=form.cleaned_data["description"],
            team_id=team_id,
        )
        token.save()

        messages.success(request, "New access token created")

        return render(
            request,
            "teams/team_tokens.html.j2",
            self._get_team_tokens_context(team, request, {"new_encoded_access_token": access_token_str}),
        )
