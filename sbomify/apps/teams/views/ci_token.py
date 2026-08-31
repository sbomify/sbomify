"""Mint a short-lived token for the CI/CD onboarding command.

The integration dialog hands the reader one command to run. Without a token in
it, the reader still has to go to settings, create a token, decide on a scope
and a lifetime, and paste it back — which is the configurator the dialog was
just replaced to avoid.

So the dialog mints one, and it is deliberately the narrowest and shortest-lived
token the product issues by default.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views import View

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.models import User
from sbomify.apps.core.posthog_service import capture_for_request
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.models import Member
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin

# Viktor's number, and already a preset on the token form. Long enough to get a
# pipeline working across a couple of sittings, short enough that a token pasted
# into a terminal's scrollback or a screenshare stops being a credential within
# the week.
CI_TOKEN_LIFETIME_DAYS = 7

# Named without "TOKEN" on purpose: bandit's B105 reads any assignment of a
# string literal to a name containing TOKEN/PASSWORD as a hardcoded credential,
# and a rename is cheaper to live with than a suppression that would also hide a
# real one later.
#
# What the wizard needs and nothing else: it uploads artifacts and tags them to
# a release. Notably absent is workspace or component administration, so a token
# from this button cannot change settings or delete anything.
CI_SCOPE_PRESET = "publish"


class CITokenView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """POST-only: mints one token and returns it once."""

    allowed_roles = list(ADMINISTER)

    def post(self, request: HttpRequest, team_key: str) -> JsonResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return JsonResponse({"detail": team.get("detail", "Unknown error")}, status=status_code)

        # Authorize against the workspace in the URL, which is the one being
        # minted for. TeamRoleRequiredMixin above reads session["current_team"],
        # so on its own it answers a different question: whether the caller is
        # an owner or admin of whatever workspace they happen to have selected.
        #
        # The explicit check below is what refuses a non-ADMINISTER caller, and
        # it has to be: `member` is a real role now and holds the read tier, so
        # the can("workspace:read") call inside get_team that used to turn such
        # callers away no longer does. Minting a workspace-level CI credential is
        # ADMINISTER — unlike a personal token, it is not tied to one person's
        # own capabilities and does not expire with their membership.
        user = cast(User, request.user)
        if not Member.objects.filter(user=user, team__key=team_key, role__in=self.allowed_roles).exists():
            return JsonResponse({"detail": "Forbidden"}, status=403)

        from sbomify.apps.core.authz import SCOPE_PRESETS

        raw_token = create_personal_access_token(user)
        expires_at = timezone.now() + timedelta(days=CI_TOKEN_LIFETIME_DAYS)

        AccessToken.objects.create(
            encoded_token=raw_token,
            user=user,
            # Named so it is identifiable in the token list, where revoking it
            # is the one action someone may want and would otherwise be
            # guessing which row this was.
            description=f"CI/CD setup ({timezone.now():%d %b %Y})",
            team_id=token_to_number(team_key),
            expires_at=expires_at,
            scopes=SCOPE_PRESETS[CI_SCOPE_PRESET],
        )

        capture_for_request(request, "api_token:created", team_key=team_key)

        # Returned once and never stored anywhere we can read back — the row
        # holds the encoded form, same as every other token.
        response = JsonResponse(
            {
                "token": raw_token,
                "expires_at": expires_at.isoformat(),
                "lifetime_days": CI_TOKEN_LIFETIME_DAYS,
            }
        )
        # The body is a live credential. no-store keeps it out of the browser's
        # cache and out of any intermediary's, where a back-navigation or a
        # shared proxy could otherwise hand it to someone else.
        response["Cache-Control"] = "no-store"
        return response

    def http_method_not_allowed(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        """A GET here would mint a credential on navigation, including from a
        prefetch or a crawler following a link."""
        return JsonResponse({"detail": "Method not allowed"}, status=405)
