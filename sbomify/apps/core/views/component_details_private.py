from __future__ import annotations

from typing import Any, cast

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.services.component_security import (
    ComponentVulnerabilitiesContext,
    build_component_vulnerabilities,
    viewer_rights,
)
from sbomify.apps.core.views.component_vulnerabilities import vulnerabilities_panel_context
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.vulnerability_scanning.services.finding_browse import parse_finding_query


class ComponentDetailsPrivateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        # On custom domains, serve public content instead
        if getattr(request, "is_custom_domain", False):
            from sbomify.apps.core.views.component_details_public import ComponentDetailsPublicView

            return ComponentDetailsPublicView.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        # get_component answers 200 for any PUBLIC or GATED component to anyone,
        # because it also serves the public read path. This page is the internal
        # one: it renders the vulnerability panel, the metadata editor and the
        # upload widget, none of which the public page shows. Without this check
        # any authenticated user could read another workspace's findings, VEX
        # dispositions and KEV flags for a published component simply by opening
        # its private URL.
        #
        # Serving the public page rather than refusing, matching the custom
        # domain branch above: a reader who followed a link to a published
        # component should land on what they are entitled to see, not on a 403.
        rights = viewer_rights(request, component_id)
        if not rights.may_see:
            from sbomify.apps.core.views.component_details_public import ComponentDetailsPublicView

            public = ComponentDetailsPublicView.as_view()(request, component_id=component_id)
            return cast("HttpResponse", public)

        current_team = request.session.get("current_team", {})
        billing_plan = current_team.get("billing_plan")

        # Get company NDA ID for visibility selector and check if gated visibility is allowed
        company_nda_id = None
        gated_visibility_allowed = False
        team_key = current_team.get("key")
        team_id = component.get("team_id")
        if team_id:
            from sbomify.apps.teams.models import Team

            try:
                team = Team.objects.get(pk=team_id)
                if not team_key:
                    team_key = team.key
                company_nda = team.get_company_nda_document()
                if company_nda:
                    company_nda_id = company_nda.id
                # Check if gated visibility is allowed (Business or Enterprise plans)
                gated_visibility_allowed = team.can_be_private()
            except Team.DoesNotExist:
                # If the referenced team no longer exists, keep the previously initialized
                # default values (no NDA, no gated visibility) and continue rendering.
                pass

        # Build mapping of document types to their subcategory choices for dynamic dropdowns
        import json

        from sbomify.apps.documents.models import Document

        document_type_subcategories = {}
        for doc_type_value, doc_type_label in Document.DocumentType.choices:
            if doc_type_value == Document.DocumentType.COMPLIANCE:
                document_type_subcategories[doc_type_value] = {
                    "field_name": "compliance_subcategory",
                    "choices": Document.ComplianceSubcategory.choices,
                    "label": "Compliance Subcategory",
                }
            # Add more document types with subcategories here as needed

        # Only BOM components render the security sections; document
        # components must not pay the artifact/scan queries for template
        # sections their page never shows.
        is_bom_component = component.get("component_type") == "bom"

        # The vulnerabilities panel: the newest SBOM's findings, summarised whole
        # for the header badge and paged for the table. Filtering and paging are
        # server-side and read from the request, so the panel's own HTMX endpoint
        # and a plain link into the page render the same state — and so a
        # component with thousands of findings ships one page of HTML instead of
        # all of them.
        vulns = (
            build_component_vulnerabilities(component_id, parse_finding_query(request.GET))
            if is_bom_component
            else ComponentVulnerabilitiesContext()
        )

        # CBOM issues drill-down: the newest crypto-bearing artifact's
        # fail/warning compliance findings (newest CBOM, else the newest mixed
        # SBOM with crypto assets). Pass/info rows are posture, not issues, so
        # they stay on the CBOM detail page.
        from sbomify.apps.core.services.component_security import CbomIssuesContext, build_latest_cbom_issues

        cbom_issues = build_latest_cbom_issues(component_id) if is_bom_component else CbomIssuesContext()

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "component": component,
            # The page header's copy chip is a list, like every other detail
            # page's, so the header component reads the same shape everywhere.
            "header_copy_values": [{"value": component_id, "title": f"Component ID: {component_id} (click to copy)"}],
            "current_team": current_team,
            "team_billing_plan": billing_plan,
            "company_nda_id": company_nda_id,
            "gated_visibility_allowed": gated_visibility_allowed,
            "team_key": team_key,
            "vuln_summary": vulns.summary,
            **vulnerabilities_panel_context(component_id, vulns, can_triage=rights.may_triage),
            "latest_cbom_issues": cbom_issues.issues,
            "latest_cbom_issue_terms": cbom_issues.terms,
            "latest_cbom_issue_severities": cbom_issues.severities,
            "latest_cbom_version": cbom_issues.artifact_version,
            "latest_cbom_id": cbom_issues.artifact_id,
            "latest_cbom_item_type": cbom_issues.artifact_item_type,
            # The upload widget validates against the same number the API
            # enforces, rather than carrying its own copy that can drift.
            "max_upload_size_mb": settings.ARTIFACT_MAX_UPLOAD_SIZE // (1024 * 1024),
            "document_type_subcategories": document_type_subcategories,
            "document_type_subcategories_json": json.dumps(document_type_subcategories),
        }

        component_type = component.get("component_type")
        if component_type == "bom":
            template_name = "core/component_details_private_sbom.html.j2"
        elif component_type == "document":
            template_name = "core/component_details_private_document.html.j2"
        else:
            return error_response(request, HttpResponse(status=400, content="Invalid component type"))

        return render(request, template_name, context)
