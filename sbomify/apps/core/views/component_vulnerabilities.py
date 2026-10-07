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
from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.services.component_security import (
    ComponentVulnerabilitiesContext,
    build_component_vulnerabilities,
    viewer_rights,
)
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.vulnerability_scanning.services.finding_browse import FindingQuery, parse_finding_query, query_string

#: The swappable region: toolbar, table and footer. The card around it is not
#: re-rendered, so the collapsible keeps its open state across a filter change.
PANEL_TEMPLATE = "core/components/component_vulnerabilities_table.html.j2"

#: The id the panel region carries, and the fragment a no-JS pager link lands on.
PANEL_ANCHOR = "component-vulnerabilities"


def vulnerabilities_panel_context(
    component_id: str, vulns: ComponentVulnerabilitiesContext, *, can_triage: bool = False
) -> dict[str, Any]:
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
        # Carried in the panel's own context rather than the page's, because the
        # table is swapped on its own and a page-level flag would not survive it.
        "can_triage": can_triage,
        "component_id": component_id,
    }
    if panel is None:
        return context

    query = panel["query"]
    context["vuln_query_string"] = query_string(query, page=1)
    # The pager's links reset to page 1; a refresh must not. This keeps the page
    # the reader is on as well as the filters, so re-rendering the panel after a
    # triage lands them back where they were.
    context["vuln_refresh_query"] = query_string(query)
    return context


class ComponentVulnerabilitiesPanelView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """One page of the component's findings, for HTMX to swap the panel with.

    Gated on ``component:manage``, not on ``get_component`` returning 200.
    ``get_component`` also serves the public read path and answers 200 for any
    PUBLIC or GATED component to anyone, so treating it as the authorization
    check would hand every authenticated user the findings, VEX dispositions and
    KEV flags of every published component in the install, none of which the
    public component page shows. See ``viewer_manages_component``.
    """

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )
        rights = viewer_rights(request, component_id)
        if not rights.may_see:
            # 404 rather than 403: for a component this reader has no business
            # with, confirming one exists at that id is itself an answer.
            return error_response(request, HttpResponse(status=404, content="Component not found"))
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
        return render(
            request,
            PANEL_TEMPLATE,
            vulnerabilities_panel_context(component_id, vulns, can_triage=rights.may_triage),
        )


class ComponentTriageModalView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Load the selected occurrence's current decision only when triage is opened."""

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        if not viewer_rights(request, component_id).may_triage:
            return htmx_error_response("Component not found")
        identity = (
            request.GET.get("advisory", ""),
            request.GET.get("package", ""),
            request.GET.get("version", ""),
            request.GET.get("ecosystem", ""),
        )
        vulns = build_component_vulnerabilities(component_id, FindingQuery(), triage_identity=identity)
        rows = vulns.panel["rows"] if vulns.panel else []
        if len(rows) != 1:
            return htmx_error_response("This vulnerability changed. Refresh the dashboard and try again.")
        finding = rows[0]
        return render(
            request,
            "core/components/priority_triage_modal.html.j2",
            {
                "component_id": component_id,
                "team_key": request.session.get("current_team", {}).get("key", ""),
                "triage_payload": {
                    "id": finding["id"],
                    "purl": finding["purl"],
                    "state": finding["vex_state"],
                    "justification": finding["vex_justification"],
                    "detail": finding["vex_detail"],
                    "aliases": ",".join(finding["aliases"]),
                },
            },
        )
