from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.forms import CreateAccessTokenForm
from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.models import User
from sbomify.apps.core.posthog_service import capture_for_request
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin


class TeamTokensView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """View for managing personal access tokens in workspace settings."""

    # Workspace-token management is owner/admin only. The previous
    # value also listed ``"member"`` — that role isn't in the canonical
    # ``TEAMS_SUPPORTED_ROLES`` choices, but Django CharField choices
    # aren't DB-enforced, so historical Member rows with
    # ``role="member"`` (fixtures, legacy migrations) were silently
    # accepted into this view. Removing it is a deliberate
    # tightening: those rows were never meant to have token-management
    # privileges, and the canonical role list is the source of truth.
    allowed_roles = ["owner", "admin"]

    def _get_team_tokens_context(
        self, team: Any, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        user = cast(User, request.user)
        team_id = token_to_number(team.key)

        # Show tokens scoped to this team + any unscoped legacy tokens
        scoped_tokens = AccessToken.objects.filter(user=user, team_id=team_id).order_by("-created_at")
        unscoped_tokens = AccessToken.objects.filter(user=user, team__isnull=True).order_by("-created_at")

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
            first_error = str(next(iter(form.errors.values()))[0])
            return htmx_error_response(first_error)

        user = cast(User, request.user)
        team_id = token_to_number(team_key)

        # PAT expiry lives in the DB row (the JWT carries no ``exp``/``aud`` —
        # those are reserved for short-lived OIDC tokens). ``get_user_and_token_record``
        # rejects a row once ``expires_at`` is in the past. ``None`` means
        # never expires (the explicit "No expiration" choice).
        expiry_days = form.expiry_days()
        expires_at = timezone.now() + timedelta(days=expiry_days) if expiry_days is not None else None

        access_token_str = create_personal_access_token(user)
        token = AccessToken(
            encoded_token=access_token_str,
            user=user,
            description=form.cleaned_data["description"],
            team_id=team_id,
            expires_at=expires_at,
        )
        token.save()

        # Token description is arbitrary user input and may contain PII
        # (customer names, copied secrets). The act of firing the event
        # is the signal we need; no description-derived properties are
        # sent. Deferred via ``on_commit`` so a rollback after
        # ``token.save()`` doesn't ship an event for a token that no
        # longer exists.
        transaction.on_commit(
            lambda: capture_for_request(
                request,
                "api_token:created",
                team_key=team_key,
            )
        )

        messages.success(request, "New access token created")

        return render(
            request,
            "teams/team_tokens.html.j2",
            self._get_team_tokens_context(team, request, {"new_encoded_access_token": access_token_str}),
        )
