from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component
from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


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

        current_team = request.session.get("current_team", {})
        is_owner = current_team.get("role") == "owner"
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

        # Latest-scan vulnerability summary for the header badge: the newest SBOM's
        # most recent completed security run (VEX-suppressed findings already
        # excluded). Tied to the newest SBOM so it matches the top artifacts row,
        # rather than whichever run happened to complete last.
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.vulnerability_scanning.utils import (
            extract_finding_rows,
            extract_severity_counts,
            merge_findings_by_alias,
        )
        from sbomify.apps.vulnerability_scanning.vex import load_vex_suppressions

        # Only BOM components render the security sections; document
        # components must not pay the artifact/scan queries for template
        # sections their page never shows.
        is_bom_component = component.get("component_type") == "bom"

        latest_sbom = (
            SBOM.objects.filter(component_id=component_id, bom_type=SBOM.BomType.SBOM)
            .order_by("-created_at")
            .values("id", "version")
            .first()
            if is_bom_component
            else None
        )
        latest_sbom_id = latest_sbom["id"] if latest_sbom else None
        latest_scan_result = (
            (
                AssessmentRun.objects.filter(sbom_id=latest_sbom_id, category="security", status="completed")
                .order_by("-created_at")
                .values_list("result", flat=True)
                .first()
            )
            if latest_sbom_id
            else None
        )
        # Flat, severity-sorted findings for the latest SBOM's drill-down table,
        # merged across every provider's latest run so aliases auto-resolve (OSV
        # carries the GHSA↔CVE mapping the DT run lacks). The component's VEX
        # resolves each finding's status live, even when the stored scan predates
        # the VEX upload.
        latest_vulns: list[dict[str, Any]] = []
        if latest_scan_result:
            provider_results = list(
                AssessmentRun.objects.filter(sbom_id=latest_sbom_id, category="security", status="completed")
                .order_by("plugin_name", "-created_at")
                .distinct("plugin_name")
                .values_list("result", flat=True)
            )
            vex_statements = load_vex_suppressions(component_id)
            latest_vulns = extract_finding_rows(merge_findings_by_alias(provider_results), vex_statements)

        # The header badge counts the same merged, VEX-filtered view the table
        # shows — counting a single run would disagree with the rows (e.g. OSV
        # rates a finding high where DT said medium).
        vuln_summary = None
        if latest_vulns:
            vuln_summary = {
                "total": len(latest_vulns),
                "critical": sum(1 for v in latest_vulns if v["severity"] == "critical"),
                "high": sum(1 for v in latest_vulns if v["severity"] == "high"),
                "medium": sum(1 for v in latest_vulns if v["severity"] == "medium"),
                "low": sum(1 for v in latest_vulns if v["severity"] == "low"),
            }
        elif latest_scan_result:
            vuln_summary = extract_severity_counts(latest_scan_result)
        # Lowercased "advisory package ecosystem" haystack per finding, so the
        # drill-down's search box can filter client-side without re-fetching.
        latest_vuln_terms = [
            f"{v['id']} {' '.join(v['aliases'])} {v['package']} {v['ecosystem']}".lower() for v in latest_vulns
        ]
        # Parallel severity list so the drill-down's type/severity dropdown can filter by index.
        latest_vuln_severities = [v["severity"] for v in latest_vulns]

        # CBOM issues drill-down: the newest crypto-bearing artifact's
        # fail/warning compliance findings (newest CBOM, else the newest mixed
        # SBOM with crypto assets). Pass/info rows are posture, not issues, so
        # they stay on the CBOM detail page.
        from sbomify.apps.core.services.component_security import CbomIssuesContext, build_latest_cbom_issues

        cbom_issues = build_latest_cbom_issues(component_id) if is_bom_component else CbomIssuesContext()

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "component": component,
            "current_team": current_team,
            "is_owner": is_owner,
            "team_billing_plan": billing_plan,
            "company_nda_id": company_nda_id,
            "gated_visibility_allowed": gated_visibility_allowed,
            "team_key": team_key,
            "vuln_summary": vuln_summary,
            "latest_vulns": latest_vulns,
            "latest_vuln_terms": latest_vuln_terms,
            "latest_vuln_severities": latest_vuln_severities,
            "latest_vuln_version": latest_sbom["version"] if latest_sbom else None,
            "latest_vuln_sbom_id": latest_sbom_id,
            "latest_cbom_issues": cbom_issues.issues,
            "latest_cbom_issue_terms": cbom_issues.terms,
            "latest_cbom_issue_severities": cbom_issues.severities,
            "latest_cbom_version": cbom_issues.artifact_version,
            "latest_cbom_id": cbom_issues.artifact_id,
            "latest_cbom_item_type": cbom_issues.artifact_item_type,
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
