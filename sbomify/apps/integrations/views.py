"""The Integrations section of workspace settings, and the OAuth callback.

Everything except the callback is `ADMINISTER`, like every other
workspace-configuration section. The callback is only ``LoginRequired``,
because at that point the browser is coming back from the provider and the
workspace it belongs to is read from the session, not from the URL; the role
is checked against that workspace before a single token is stored.
"""

from __future__ import annotations

from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.models import User
from sbomify.apps.integrations import oauth
from sbomify.apps.integrations.exceptions import ProviderAuthError
from sbomify.apps.integrations.providers import get_provider
from sbomify.apps.integrations.services import connections
from sbomify.apps.integrations.tasks import sync_integration
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.utils import redirect_to_team_settings
from sbomify.logging import getLogger

logger = getLogger(__name__)

SETTINGS_TAB = "integrations"


def _team_or_none(team_key: str) -> Team | None:
    return Team.objects.filter(key=team_key).first()


class IntegrationsView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """The tab body, loaded over HTMX, plus its two POST actions."""

    allowed_roles = list(ADMINISTER)

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        team = _team_or_none(team_key)
        if team is None:
            return htmx_error_response("Workspace not found")

        return render(
            request,
            "integrations/integrations_panel.html.j2",
            {
                "team": team,
                "cards": connections.provider_cards(team),
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        team = _team_or_none(team_key)
        if team is None:
            return htmx_error_response("Workspace not found")

        action = request.POST.get("action", "")

        if action == "disconnect":
            return self._disconnect(request, team)
        if action == "sync":
            return self._sync(request, team)
        if action == "publish":
            return self._publish(request, team)

        return htmx_error_response("Unknown action")

    def _disconnect(self, request: HttpRequest, team: Team) -> HttpResponse:
        provider_key = request.POST.get("provider", "")
        provider = get_provider(provider_key)
        if provider is None:
            return htmx_error_response("Unknown integration")

        result = connections.disconnect(team, provider.key)
        if not result.ok:
            return htmx_error_response(result.error or "Could not disconnect")

        return htmx_success_response(
            f"Disconnected {provider.name}. Its frameworks are no longer on your Trust Center.",
            triggers={"refreshIntegrations": True},
        )

    def _sync(self, request: HttpRequest, team: Team) -> HttpResponse:
        provider_key = request.POST.get("provider", "")
        provider = get_provider(provider_key)
        if provider is None:
            return htmx_error_response("Unknown integration")

        integration = connections.get_integration(team, provider.key)
        if integration is None:
            return htmx_error_response(f"{provider.name} is not connected")

        # Queued, not run: a sync is one request per control against someone
        # else's API, which is not something a page load can wait for.
        sync_integration.send(integration.id)
        return htmx_success_response(
            f"Syncing {provider.name}. Reload this page in a minute to see the result.",
            triggers={"refreshIntegrations": True},
        )

    def _publish(self, request: HttpRequest, team: Team) -> HttpResponse:
        catalog_id = request.POST.get("catalog_id", "")
        published = request.POST.get("published") == "true"

        result = connections.set_catalog_published(team, catalog_id, published)
        if not result.ok:
            return htmx_error_response(result.error or "Could not update the framework")

        verb = "now on" if published else "no longer on"
        return htmx_success_response(
            f"{result.value} is {verb} your Trust Center.",
            triggers={"refreshIntegrations": True},
        )


class IntegrationConnectView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Start the OAuth flow for one provider."""

    allowed_roles = list(ADMINISTER)

    def post(self, request: HttpRequest, team_key: str, provider: str) -> HttpResponse:
        spec = get_provider(provider)
        if spec is None:
            messages.error(request, "Unknown integration")
            return redirect_to_team_settings(team_key, SETTINGS_TAB)

        if not spec.is_configured:
            messages.error(request, f"{spec.name} is not available on this deployment.")
            return redirect_to_team_settings(team_key, SETTINGS_TAB)

        return HttpResponseRedirect(oauth.start_authorization(request, spec, team_key))


class IntegrationCallbackView(LoginRequiredMixin, View):
    """Where the provider sends the browser back.

    One fixed URL per provider with no workspace in it, because that is what a
    provider will let you register. The workspace comes from the session entry
    that ``start_authorization`` wrote, which is also the CSRF check.
    """

    def get(self, request: HttpRequest, provider: str) -> HttpResponse:
        spec = get_provider(provider)
        if spec is None:
            messages.error(request, "Unknown integration")
            return redirect("core:dashboard")

        state = request.GET.get("state", "")
        team_key = oauth.consume_state(request, spec, state)
        if team_key is None:
            messages.error(request, "That connection link has expired. Start again from Settings.")
            return redirect("core:dashboard")

        # The provider reports a refusal by sending the user back with an
        # error rather than a code. Handled after the state check so a stray
        # callback cannot put arbitrary text in front of a user.
        if request.GET.get("error"):
            messages.error(request, f"{spec.name} did not grant access.")
            return redirect_to_team_settings(team_key, SETTINGS_TAB)

        code = request.GET.get("code", "")
        if not code:
            messages.error(request, f"{spec.name} did not return an authorization code.")
            return redirect_to_team_settings(team_key, SETTINGS_TAB)

        team = _team_or_none(team_key)
        user = cast(User, request.user)
        # Re-checked here rather than trusted from the session: the flow can
        # take as long as the provider's sign-in does, and the role that
        # started it may not be the role that comes back.
        if team is None or not Member.objects.filter(user=user, team=team, role__in=ADMINISTER).exists():
            messages.error(request, "You cannot manage integrations for that workspace.")
            return redirect("core:dashboard")

        try:
            token_set = oauth.exchange_code(request, spec, code)
        except ProviderAuthError as exc:
            logger.warning("Token exchange failed for %s: %s", spec.key, exc.detail)
            messages.error(request, exc.detail)
            return redirect_to_team_settings(team_key, SETTINGS_TAB)

        integration = connections.save_connection(team, spec, token_set, user)
        sync_integration.send(integration.id)

        messages.success(
            request,
            f"Connected {spec.name}. Your frameworks appear here once the first sync finishes.",
        )
        return redirect_to_team_settings(team_key, SETTINGS_TAB)
