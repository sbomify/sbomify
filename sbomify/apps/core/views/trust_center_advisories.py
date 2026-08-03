"""Security advisories on the trust center.

The workspace-side views in ``security_advisories.py`` are behind
``LoginRequiredMixin`` and show everything a workspace has written down. These
two are the outward face of the same records: anonymous by default, and filtered
by :mod:`security_advisories.services.trust_center` so a reader is shown only
what their access actually entitles them to.

Nothing here decides visibility itself — the service does, in one place, so the
list and the detail page cannot disagree about a given advisory.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.url_utils import (
    build_custom_domain_url,
    should_redirect_to_clean_url,
    should_redirect_to_custom_domain,
)
from sbomify.apps.core.views.workspace_public import fetch_public_team
from sbomify.apps.security_advisories.services.trust_center import (
    browse_public_advisories,
    get_public_advisory,
    parse_advisory_query,
)
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


def _querystrings(request: HttpRequest, query: Any) -> dict[str, str]:
    """Reusable query fragments for the pager.

    The sidebar is a plain GET form, so its own controls need no help — the
    browser serialises them. The pager links sit outside that form, though, and
    a link that dropped the active filters would silently reset them, so it
    carries every current parameter except ``page``.
    """
    params = request.GET.copy()
    params.pop("page", None)
    encoded = params.urlencode()
    return {"without_page": f"{encoded}&" if encoded else ""}


class _TrustCenterAdvisoryViewBase(View):
    """Shared workspace resolution and branding for the two advisory pages."""

    def _resolve(self, request: HttpRequest, workspace_key: str | None) -> tuple[Team | None, HttpResponse | None]:
        status_code, team_or_error = fetch_public_team(request, workspace_key)
        if status_code != 200 or not isinstance(team_or_error, Team):
            detail = team_or_error.get("detail", "Workspace not found")  # type: ignore[union-attr]
            return None, error_response(request, HttpResponseNotFound(detail))
        return team_or_error, None

    def _redirect_if_needed(self, request: HttpRequest, team: Team, path: str) -> HttpResponse | None:
        if should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request):
            return HttpResponseRedirect(build_custom_domain_url(team, path, request.is_secure()))
        return None

    def _base_context(self, request: HttpRequest, team: Team) -> dict[str, Any]:
        return {
            "brand": build_branding_context(team),
            "workspace": {"name": team.display_name, "key": team.key},
            "is_custom_domain": getattr(request, "is_custom_domain", False),
        }


class TrustCenterAdvisoriesView(_TrustCenterAdvisoryViewBase):
    """The workspace's public advisory feed."""

    def get(self, request: HttpRequest, workspace_key: str | None = None) -> HttpResponse:
        team, error = self._resolve(request, workspace_key)
        if error is not None or team is None:
            return error  # type: ignore[return-value]

        redirect = self._redirect_if_needed(request, team, "/advisories/")
        if redirect is not None:
            return redirect

        query = parse_advisory_query(request.GET)
        payload = browse_public_advisories(request, team, query).value or {}

        return render(
            request,
            "core/trust_center_advisories.html.j2",
            {
                **self._base_context(request, team),
                **payload,
                # The sidebar and pager rebuild the current URL with one
                # parameter changed, so they need everything except the one they
                # are replacing. Prebuilt here rather than assembled in the
                # template, where dropping a parameter silently loses a filter.
                "querystrings": _querystrings(request, query),
                "search": query.search,
            },
        )


class TrustCenterAdvisoryDetailView(_TrustCenterAdvisoryViewBase):
    """One advisory as a customer reads it.

    A gated advisory the reader may not see 404s rather than 403s — the service
    makes that call, because a 403 would confirm the advisory exists.
    """

    def get(self, request: HttpRequest, advisory_id: str, workspace_key: str | None = None) -> HttpResponse:
        team, error = self._resolve(request, workspace_key)
        if error is not None or team is None:
            return error  # type: ignore[return-value]

        redirect = self._redirect_if_needed(request, team, f"/advisories/{advisory_id}/")
        if redirect is not None:
            return redirect

        result = get_public_advisory(request, team, advisory_id)
        if not result.ok or result.value is None:
            return error_response(request, HttpResponseNotFound("Advisory not found"))

        return render(
            request,
            "core/trust_center_advisory_detail.html.j2",
            {**self._base_context(request, team), "advisory": result.value},
        )
