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
from urllib.parse import quote, urlparse

from django.conf import settings
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


def _public_hosts_for(team: Team) -> set[str]:
    """Every host this workspace may legitimately be redirected to.

    Mirrors the two branches of ``build_custom_domain_url``: a validated custom
    domain, and the trust-center subdomain. Both are derived from the team rather
    than from anything on the request, so the set cannot be widened by a visitor.
    """
    hosts: set[str] = set()
    custom_domain = getattr(team, "custom_domain", "")
    if custom_domain and getattr(team, "custom_domain_validated", False):
        hosts.add(custom_domain.lower())

    slug = getattr(team, "slug", None)
    trust_center_domain = getattr(settings, "TRUST_CENTER_DOMAIN", "")
    if slug and trust_center_domain:
        hosts.add(f"{slug}.{trust_center_domain}".lower())
    return hosts


class _TrustCenterAdvisoryViewBase(View):
    """Shared workspace resolution and branding for the two advisory pages."""

    def _resolve(self, request: HttpRequest, workspace_key: str | None) -> tuple[Team | None, HttpResponse | None]:
        status_code, team_or_error = fetch_public_team(request, workspace_key)
        if status_code != 200 or not isinstance(team_or_error, Team):
            # A fixed string rather than the resolver's dict value: every failure
            # path it has returns this same message, so echoing the lookup back
            # gained nothing and put request-derived data on an error page for a
            # scanner to flag. It also drops a type: ignore.
            return None, error_response(request, HttpResponseNotFound("Workspace not found"))
        return team_or_error, None

    def _redirect_if_needed(self, request: HttpRequest, team: Team, path: str) -> HttpResponse | None:
        """Send the reader to this workspace's own public domain, or nowhere.

        The redirect host comes from ``team.custom_domain``, which a workspace
        owner types in — a stored value that reaches a ``Location`` header. It is
        meant to be constrained already: ``build_custom_domain_url`` only uses a
        custom domain once ``custom_domain_validated`` is set. But that guard
        lives in another module, and "the URL we are about to send you to is
        safe because of a flag checked elsewhere" is exactly the kind of
        reasoning that rots when one of the two sides is edited.

        So the built URL is checked here against the hosts this team is actually
        entitled to, recomputed from the same team. A target that is not one of
        them is not redirected to at all, rather than trusted because of where it
        came from.
        """
        if not (should_redirect_to_custom_domain(request, team) or should_redirect_to_clean_url(request)):
            return None

        target = build_custom_domain_url(team, path, request.is_secure())
        if not target:
            return None
        if (urlparse(target).hostname or "").lower() not in _public_hosts_for(team):
            return None
        return HttpResponseRedirect(target)

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
        context = {
            **self._base_context(request, team),
            **payload,
            # The pager rebuilds the current URL with one parameter changed, so
            # it needs everything except the one it is replacing. Prebuilt here
            # rather than assembled in the template, where dropping a parameter
            # silently loses a filter.
            "querystrings": _querystrings(request, query),
            "search": query.search,
        }

        # Ticking a facet re-renders only the browse region, so the page does
        # not flash and the reader keeps their place. The full page is still the
        # canonical response — the same template is embedded in it, and the form
        # remains a plain GET form for anyone without JavaScript.
        if request.headers.get("HX-Request"):
            return render(request, "core/components/trust_center/advisories_browse.html.j2", context)

        return render(request, "core/trust_center_advisories.html.j2", context)


class TrustCenterAdvisoryDetailView(_TrustCenterAdvisoryViewBase):
    """One advisory as a customer reads it.

    A gated advisory the reader may not see 404s rather than 403s — the service
    makes that call, because a 403 would confirm the advisory exists.
    """

    def get(self, request: HttpRequest, advisory_id: str, workspace_key: str | None = None) -> HttpResponse:
        team, error = self._resolve(request, workspace_key)
        if error is not None or team is None:
            return error  # type: ignore[return-value]

        # The id is percent-encoded before it reaches the redirect target. It
        # arrives straight off the URL and this runs before the advisory is
        # looked up, so at this point it is an arbitrary string rather than a
        # known id — and a redirect target is the wrong place to find that out.
        # The <str:...> converter already excludes slashes, so a host cannot be
        # forged, but "?" and "#" would still change where the URL points.
        redirect = self._redirect_if_needed(request, team, f"/advisories/{quote(advisory_id, safe='')}/")
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
