from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component, list_component_documents, list_component_sboms
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import calculate_ntia_compliance_summary


class ComponentDetailsPrivateView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=component.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team", {})
        is_owner = current_team.get("role") == "owner"
        billing_plan = current_team.get("billing_plan")

        context = {
            "APP_BASE_URL": settings.APP_BASE_URL,
            "component": component,
            "current_team": current_team,
            "is_owner": is_owner,
            "team_billing_plan": billing_plan,
        }

        if component.get("component_type") == Component.ComponentType.SBOM:
            status_code, sboms_response = list_component_sboms(request, component_id, page=1, page_size=-1)
            if status_code != 200:
                return error_response(
                    request, HttpResponse(status=status_code, content=sboms_response.get("detail", "Unknown error"))
                )
            context["sboms_data"] = sboms_response.get("items", [])

            sbom_queryset = (
                SBOM.objects.filter(component_id=component_id)
                .only("id", "ntia_compliance_status", "ntia_compliance_details", "ntia_compliance_checked_at")
                .order_by()
            )
            ntia_summary = calculate_ntia_compliance_summary(sbom_queryset)
            ntia_summary.update(
                {
                    "scope": "component",
                    "scope_id": component_id,
                    "scope_name": component.get("name"),
                }
            )

            # Aggregate vulnerability data from latest scan results
            from django.db.models import F, OuterRef, Subquery, Sum

            from sbomify.apps.vulnerability_scanning.models import VulnerabilityScanResult

            sbom_ids = list(sbom_queryset.values_list("id", flat=True))
            if sbom_ids:
                # Get the latest scan result for each SBOM and aggregate

                latest_scan_subquery = (
                    VulnerabilityScanResult.objects.filter(sbom_id=OuterRef("sbom_id"))
                    .order_by("-created_at")
                    .values("created_at")[:1]
                )
                latest_scan_ids = (
                    VulnerabilityScanResult.objects.filter(sbom_id__in=sbom_ids)
                    .annotate(latest_created_at=Subquery(latest_scan_subquery))
                    .filter(created_at=F("latest_created_at"))
                    .values_list("id", flat=True)
                )
                vuln_totals = VulnerabilityScanResult.objects.filter(id__in=latest_scan_ids).aggregate(
                    critical=Sum("critical_vulnerabilities"),
                    high=Sum("high_vulnerabilities"),
                    medium=Sum("medium_vulnerabilities"),
                    low=Sum("low_vulnerabilities"),
                )
                ntia_summary["vulnerabilities"] = {
                    "critical": vuln_totals["critical"] or 0,
                    "high": vuln_totals["high"] or 0,
                    "medium": vuln_totals["medium"] or 0,
                    "low": vuln_totals["low"] or 0,
                }

            context["ntia_component_summary"] = ntia_summary

        elif component.get("component_type") == Component.ComponentType.DOCUMENT:
            status_code, documents_response = list_component_documents(request, component_id, page=1, page_size=-1)
            if status_code != 200:
                return error_response(
                    request, HttpResponse(status=status_code, content=documents_response.get("detail", "Unknown error"))
                )
            context["documents_data"] = documents_response.get("items", [])

        else:
            return error_response(request, HttpResponseNotFound("Unknown component type"))

        return render(request, "core/component_details_private.html.j2", context)
