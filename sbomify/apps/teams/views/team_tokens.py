from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.forms import CreateAccessTokenForm
from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin


class TeamTokensView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """View for managing personal access tokens in workspace settings."""

    allowed_roles = ["owner", "admin", "member"]

    def _get_team_tokens_context(self, team: dict, request: HttpRequest, extra_context: dict = None) -> dict:
        # Return queryset objects directly for Django template rendering
        access_tokens = AccessToken.objects.filter(user=request.user).order_by("-created_at")

        context = {
            "team": team,
            "create_access_token_form": CreateAccessTokenForm(),
            "access_tokens": access_tokens,
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
            return htmx_error_response(form.errors.as_text())

        access_token_str = create_personal_access_token(request.user)
        token = AccessToken(
            encoded_token=access_token_str,
            user=request.user,
            description=form.cleaned_data["description"],
        )
        token.save()

        messages.success(request, "New access token created")

        return render(
            request,
            "teams/team_tokens.html.j2",
            self._get_team_tokens_context(team, request, {"new_encoded_access_token": access_token_str}),
        )
