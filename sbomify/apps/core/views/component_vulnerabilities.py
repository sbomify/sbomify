"""The component page's vulnerabilities panel, as its own endpoint.

The panel searches, filters and pages on the server, so every one of those
actions is a request. Routing them back through the component detail view would
make a keystroke in the search box rebuild the header, the artifacts table, the
metadata editor and the CBOM panel as well; this view resolves the one region
that changed and returns just its markup.

The panel is the workspace Vulnerabilities list scoped to this component: one
row per vulnerability, scanners merged by alias, with triage and a fix prompt.
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
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.vary import vary_on_headers

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.htmx import HtmxFragmentMixin, htmx_error_response
from sbomify.apps.core.services.component_security import build_component_vulnerabilities, viewer_rights
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.vulnerability_scanning.services.finding_browse import FindingQuery
from sbomify.apps.vulnerability_scanning.services.workspace_vulnerabilities import build_component_vulnerability_list

#: The swappable region: toolbar and results. The card around it is not
#: re-rendered, so the collapsible keeps its open state across a filter change.
PANEL_TEMPLATE = "core/components/component_vulnerabilities_table.html.j2"

#: The results alone: what the pager and a triage refresh swap.
RESULTS_TARGET = "component-vulnerabilities-results"
RESULTS_TEMPLATE = "core/components/component_vulnerabilities_results.html.j2"

#: The id the panel region carries, and the fragment a no-JS pager link lands on.
PANEL_ANCHOR = "component-vulnerabilities"

SEVERITY_CHOICES = (
    ("critical", "Critical"),
    ("high", "High"),
    ("medium", "Medium"),
    ("low", "Low"),
    ("other", "Other"),
)


def component_vulnerability_list(
    request: HttpRequest, component_id: str, workspace_key: str, *, can_triage: bool
) -> dict[str, Any]:
    """The workspace Vulnerabilities list scoped to this component, posting back to its panel endpoint.

    The first render of the page and the panel endpoint both build their context here.
    """
    result = build_component_vulnerability_list(
        workspace_key,
        component_id,
        request.GET,
        base_url=reverse("core:component_vulnerabilities_panel", args=[component_id]),
        can_triage=can_triage,
    )
    return {"vuln_data": result.value or {}, "component_id": component_id, "severity_choices": SEVERITY_CHOICES}


class ComponentVulnerabilitiesPanelView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """One page of the component's findings, for HTMX to swap the panel with.

    Gated on ``component:manage``, not on ``get_component`` returning 200.
    ``get_component`` also serves the public read path and answers 200 for any
    PUBLIC or GATED component to anyone, so treating it as the authorization
    check would hand every authenticated user the findings, VEX dispositions and
    KEV flags of every published component in the install, none of which the
    public component page shows. See ``viewer_manages_component``.
    """

    # The panel and its results-only fragment share a URL, told apart by HX-Target.
    @method_decorator(vary_on_headers("HX-Target", "HX-Request"))
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

        # The header rather than django-htmx's request.htmx: the middleware that
        # sets that attribute is not in the test settings, and reading what HTMX
        # actually sends needs no middleware at all.
        if not request.headers.get("HX-Request"):
            page_url = reverse("core:component_details", args=[component_id])
            return HttpResponseRedirect(f"{page_url}?{request.GET.urlencode()}#{PANEL_ANCHOR}")

        template = RESULTS_TEMPLATE if request.headers.get("HX-Target") == RESULTS_TARGET else PANEL_TEMPLATE
        return render(
            request,
            template,
            component_vulnerability_list(request, component_id, rights.team_key, can_triage=rights.may_triage),
        )


class ComponentTriageModalView(HtmxFragmentMixin, GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Load the selected occurrence's current decision only when triage is opened."""

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        rights = viewer_rights(request, component_id)
        if not rights.may_triage:
            return htmx_error_response("Component not found")
        identity = (
            request.GET.get("advisory", ""),
            request.GET.get("package", ""),
            request.GET.get("version", ""),
            request.GET.get("ecosystem", ""),
            request.GET.get("purl", ""),
        )
        # The SBOM the row was read from: the list can show a release's or an older version's findings.
        vulns = build_component_vulnerabilities(
            component_id, FindingQuery(), triage_identity=identity, sbom_id=request.GET.get("sbom") or None
        )
        rows = vulns.panel["rows"] if vulns.panel else []
        if len(rows) != 1:
            return htmx_error_response("This vulnerability changed. Refresh the dashboard and try again.")
        finding = rows[0]
        return render(
            request,
            "core/components/priority_triage_modal.html.j2",
            {
                "component_id": component_id,
                "team_key": rights.team_key,
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
