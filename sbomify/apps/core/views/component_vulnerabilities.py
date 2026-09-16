"""The component page's vulnerabilities panel, as its own endpoint.

The panel searches, filters and pages on the server, so every one of those
actions is a request. Routing them back through the component detail view would
make a keystroke in the search box rebuild the header, the artifacts table, the
metadata editor and the CBOM panel as well; this view resolves the one region
that changed and returns just its markup.

The first render of the page goes through the same context builder, so the two
cannot disagree about what a filter means.

One URL serves both audiences. An HTMX request gets the region; a plain one — a
pager link followed with JavaScript off, or a shared URL — is redirected to the
component page carrying the same parameters, which renders the same state in
full. That is what lets every control in the panel carry a single ``href`` and
still work either way.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.services.component_security import (
    ComponentVulnerabilitiesContext,
    build_component_vulnerabilities,
)
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.vulnerability_scanning.services.finding_browse import parse_finding_query, query_string

#: The swappable region: toolbar, table and footer. The card around it is not
#: re-rendered, so the collapsible keeps its open state across a filter change.
PANEL_TEMPLATE = "core/components/component_vulnerabilities_table.html.j2"

#: The id the panel region carries, and the fragment a no-JS pager link lands on.
PANEL_ANCHOR = "component-vulnerabilities"


def vulnerabilities_panel_context(component_id: str, vulns: ComponentVulnerabilitiesContext) -> dict[str, Any]:
    """Everything the panel template renders, including the URLs it posts back to.

    The pager links sit outside the filter form, so they carry the active filters
    in their own querystring: following one must not silently clear the search
    box.
    """
    panel = vulns.panel
    panel_url = reverse("core:component_vulnerabilities_panel", args=[component_id])
    context: dict[str, Any] = {
        "vuln_panel": panel,
        "vuln_panel_url": panel_url,
        "latest_vuln_version": vulns.version,
        "latest_vuln_sbom_id": vulns.sbom_id,
    }
    if panel is None:
        return context

    query = panel["query"]
    context["vuln_prev_url"] = f"{panel_url}?{query_string(query, page=panel['prev_page'])}"
    context["vuln_next_url"] = f"{panel_url}?{query_string(query, page=panel['next_page'])}"
    return context


class ComponentVulnerabilitiesPanelView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """One page of the component's findings, for HTMX to swap the panel with.

    Access is resolved through ``get_component`` rather than re-derived here, so
    this endpoint grants exactly what the page it belongs to grants: a component
    a reader may not open does not become readable a region at a time.
    """

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )
        if component.get("component_type") != "bom":
            return error_response(request, HttpResponse(status=404, content="Component has no vulnerabilities"))

        query = parse_finding_query(request.GET)
        # The header rather than django-htmx's request.htmx: the middleware that
        # sets that attribute is not in the test settings, and reading what HTMX
        # actually sends needs no middleware at all.
        if not request.headers.get("HX-Request"):
            page_url = reverse("core:component_details", args=[component_id])
            return HttpResponseRedirect(f"{page_url}?{query_string(query)}#{PANEL_ANCHOR}")

        vulns = build_component_vulnerabilities(component_id, query)
        return render(request, PANEL_TEMPLATE, vulnerabilities_panel_context(component_id, vulns))
