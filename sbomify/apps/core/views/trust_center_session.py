"""Hand a signed-in reader over from the app domain to a Trust Center host.

See ``core/services/trust_center_session.py`` for why the handoff exists and
what the session it creates may do.
"""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit

from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.services.trust_center_session import (
    SESSION_HOST_KEY,
    issue_handoff_token,
    redeem_handoff_token,
)
from sbomify.apps.core.url_utils import build_custom_domain_url, custom_domain_redirect
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Workspace
from sbomify.apps.teams.utils import normalize_host


def safe_next_path(next_path: str | None) -> str:
    """A path on the current host to land on, or the Trust Center home."""
    if next_path and next_path.startswith("/") and url_has_allowed_host_and_scheme(next_path, allowed_hosts=None):
        return next_path
    return "/"


class TrustCenterSignInView(LoginRequiredMixin, View):
    """On the app domain: confirm, then send the reader to the Trust Center signed in."""

    @staticmethod
    def _trust_center(request: HttpRequest, workspace_key: str) -> tuple[Workspace, str] | None:
        """The workspace and the host its Trust Center is served from."""
        # Only ever handed out from the app domain, where the reader's session lives.
        if getattr(request, "is_custom_domain", False):
            return None
        team = Workspace.objects.filter(key=workspace_key).first()
        if team is None:
            return None
        url = build_custom_domain_url(team, "/", request.is_secure())
        if not url:
            return None
        return team, normalize_host(urlsplit(url).netloc)

    def get(self, request: HttpRequest, workspace_key: str) -> HttpResponse:
        trust_center = self._trust_center(request, workspace_key)
        if trust_center is None:
            return error_response(request, HttpResponseNotFound("Trust Center not found"))
        team, host = trust_center

        return render(
            request,
            "core/trust_center_sign_in.html.j2",
            {
                "brand": build_branding_context(team),
                "workspace_name": team.display_name,
                "host": host,
                "next": safe_next_path(request.GET.get("next")),
            },
        )

    def post(self, request: HttpRequest, workspace_key: str) -> HttpResponse:
        trust_center = self._trust_center(request, workspace_key)
        if trust_center is None:
            return error_response(request, HttpResponseNotFound("Trust Center not found"))
        team, host = trust_center

        query = urlencode(
            {
                "token": issue_handoff_token(request.user, team, host),
                "next": safe_next_path(request.POST.get("next")),
            }
        )
        # custom_domain_redirect refuses any host that is not this workspace's own.
        response = custom_domain_redirect(team, f"{reverse('core:trust_center_session')}?{query}", request.is_secure())
        if response is None:
            return error_response(request, HttpResponseNotFound("Trust Center not found"))
        return response


class TrustCenterSessionView(View):
    """On the Trust Center host: redeem the handoff token and sign the reader in."""

    def get(self, request: HttpRequest) -> HttpResponse:
        if not getattr(request, "is_custom_domain", False):
            return error_response(request, HttpResponseNotFound("Not found"))

        user_id = redeem_handoff_token(request.GET.get("token", ""), request)
        user = (
            get_user_model().objects.filter(pk=user_id, is_active=True, deleted_at__isnull=True).first()
            if user_id is not None
            else None
        )
        if user is None:
            return error_response(
                request, HttpResponseBadRequest("This sign-in link has expired. Please sign in again.")
            )

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session[SESSION_HOST_KEY] = normalize_host(request.get_host())

        response = redirect(safe_next_path(request.GET.get("next")))
        # The token is spent, but keep it out of the next page's Referer anyway.
        response["Referrer-Policy"] = "no-referrer"
        return response


def trust_center_sign_in_url(request: HttpRequest, next_path: str | None) -> str | None:
    """Where a Trust Center host sends a reader who wants to sign in, if it is one."""
    from django.conf import settings

    team = getattr(request, "custom_domain_team", None)
    if not getattr(request, "is_custom_domain", False) or team is None or not settings.APP_BASE_URL:
        return None
    path = reverse("core:trust_center_sign_in", kwargs={"workspace_key": team.key})
    return f"{settings.APP_BASE_URL.rstrip('/')}{path}?{urlencode({'next': safe_next_path(next_path)})}"
