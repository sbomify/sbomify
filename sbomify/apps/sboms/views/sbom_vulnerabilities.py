import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin

logger = logging.getLogger(__name__)


class SbomVulnerabilitiesView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        try:
            sbom: SBOM = SBOM.objects.get(pk=sbom_id)
        except SBOM.DoesNotExist:
            return error_response(request, HttpResponseNotFound("SBOM not found"))

        if not verify_item_access(request, sbom, ["owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

        vulnerabilities_data = None
        scan_timestamp_str = None
        error_message = None
        error_details = None
        is_processing = False
        processing_message = None
        sbom_version_info = None
        latest_result = None

        try:
            # Fetch the latest security assessment run for this SBOM
            latest_result = (
                AssessmentRun.objects.filter(
                    sbom=sbom,
                    category="security",
                    status="completed",
                )
                .order_by("-created_at")
                .first()
            )

            if latest_result:
                result_json = latest_result.result or {}
                scan_timestamp_str = latest_result.created_at.strftime("%B %d, %Y at %I:%M %p %Z")

                sbom_version_info = {
                    "name": sbom.name,
                    "version": sbom.version,
                    "component_name": sbom.component.name,
                    "format": sbom.format,
                    "format_version": sbom.format_version,
                    "source": sbom.source_display,
                }

                # Extract findings from the result JSON
                findings = result_json.get("findings", [])

                if isinstance(findings, list) and findings:
                    vulnerabilities_data = {
                        "results": [
                            {"source": {"file_path": f"{sbom.name} ({latest_result.plugin_name})"}, "packages": []}
                        ]
                    }

                    # Group vulnerabilities by component/package for display
                    packages_dict = {}
                    for vuln in findings:
                        component = vuln.get("component", {})
                        package_name = component.get("name", "Unknown Package")
                        package_version = component.get("version", "Unknown Version")
                        package_ecosystem = component.get("ecosystem", "Unknown")
                        if not package_ecosystem or package_ecosystem in ["Unknown", "unknown"]:
                            purl = component.get("purl", "")
                            if purl and purl.startswith("pkg:"):
                                try:
                                    package_ecosystem = purl.split(":")[1].split("/")[0]
                                except (IndexError, AttributeError):
                                    package_ecosystem = "Unknown"

                        package_key = f"{package_name}:{package_version}:{package_ecosystem}"

                        if package_key not in packages_dict:
                            packages_dict[package_key] = {
                                "package": {
                                    "name": package_name,
                                    "version": package_version,
                                    "ecosystem": package_ecosystem,
                                },
                                "vulnerabilities": [],
                            }

                        template_vuln = {
                            "id": vuln.get("id", "Unknown"),
                            "aliases": vuln.get("aliases", []),
                            "summary": vuln.get("title") or vuln.get("summary", ""),
                            "details": vuln.get("description", ""),
                            "severity": vuln.get("severity", "medium"),
                            "cvss_score": vuln.get("cvss_score"),
                            "references": vuln.get("references", []),
                            "source": vuln.get("source", "Unknown"),
                            "affected": vuln.get("affected", []),
                        }

                        packages_dict[package_key]["vulnerabilities"].append(template_vuln)

                    vulnerabilities_data["results"][0]["packages"] = list(packages_dict.values())

                # Check for error metadata
                metadata = result_json.get("metadata", {})
                if metadata.get("error"):
                    error_message = "An error occurred during vulnerability scanning"
                    # Check findings for error details
                    for f in findings:
                        if f.get("status") == "error":
                            error_message = f.get("description", error_message)
                            break

        except Exception as e:
            error_message = f"An unexpected error occurred while fetching vulnerability data: {str(e)}"
            logger.error(f"Unexpected error in sbom_vulnerabilities view for SBOM {sbom_id}: {e}", exc_info=True)

        return render(
            request,
            "sboms/sbom_vulnerabilities.html.j2",
            {
                "sbom": sbom,
                "vulnerabilities": vulnerabilities_data,
                "scan_timestamp": scan_timestamp_str,
                "sbom_version_info": sbom_version_info,
                "error_message": error_message,
                "error_details": error_details,
                "APP_BASE_URL": settings.APP_BASE_URL,
                "team_billing_plan": getattr(sbom.component.team, "billing_plan", "community"),
                "is_processing": is_processing,
                "processing_message": processing_message,
                "processing_provider": latest_result.plugin_name.replace("-", " ").title()
                if latest_result and is_processing
                else None,
            },
        )
