from __future__ import annotations

import json
from datetime import timedelta
from functools import partial
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
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
            scopes=form.scopes(),
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

    def delete(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Bulk-revoke the caller's tokens (#1061).

        Owner/admin gate + workspace scoping come from TeamRoleRequiredMixin + get_team.
        Only the caller's own tokens are ever deleted: an explicit list with any id not
        owned by the caller is rejected wholesale (mirrors the single-delete 403), and
        revoke-all targets exactly what this page shows (this team's tokens + the
        unscoped legacy ones).
        """
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            # delete() is called via fetch (JSON), not HTMX -- return a JSON error.
            return JsonResponse({"detail": team.get("detail", "Unknown error")}, status=status_code)

        user = cast(User, request.user)
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Invalid JSON"}, status=400)
        if not isinstance(payload, dict):
            # json.loads can return a list/None/str; .get would then 500.
            return JsonResponse({"detail": "Invalid JSON: expected an object"}, status=400)

        # Scope to exactly what this page manages: the caller's tokens in THIS workspace
        # plus the unscoped legacy ones. Without the team filter, crafted ids could revoke
        # the caller's tokens in OTHER workspaces -- tokens this page never shows.
        # Use the team_key path param (already a valid token) rather than the nullable
        # team.key DB field, which would 500 on token_to_number if null.
        team_id = token_to_number(team_key)
        tokens = AccessToken.objects.filter(user=user).filter(Q(team_id=team_id) | Q(team__isnull=True))
        if payload.get("all") is not True:
            ids = payload.get("token_ids")
            # Reject non-int ids (strings would crash the id__in cast) and require a real
            # boolean for "all" (a truthy string like "false" must not mean revoke-all).
            if (
                not isinstance(ids, list)
                or not ids
                or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
            ):
                return JsonResponse({"detail": "token_ids must be a non-empty list of integers"}, status=400)
            tokens = tokens.filter(id__in=ids)
            # Any requested id not in this page's scoped set (foreign user, other
            # workspace, or nonexistent) -> reject wholesale, same shape as single-delete.
            if tokens.count() != len(set(ids)):
                return JsonResponse({"detail": "Not allowed"}, status=403)

        # Capture scoped tokens' team keys before deletion for the PostHog event.
        # Team keys of the scoped tokens (one per token, duplicates kept) without
        # loading model instances.
        scoped_team_keys = list(tokens.filter(team__isnull=False).values_list("team__key", flat=True))
        with transaction.atomic():
            tokens.delete()
            # Register inside the atomic block so the event is tied to THIS transaction
            # (registered after it exits, on_commit fires immediately in autocommit mode).
            # Unscoped (team is None) deletions are intentionally not captured, matching
            # the single-delete convention; partial binds team_key per iteration.
            for token_team_key in scoped_team_keys:
                transaction.on_commit(
                    partial(capture_for_request, request, "api_token:deleted", team_key=token_team_key)
                )

        return HttpResponse(status=200)
