from __future__ import annotations

import logging
import typing

if typing.TYPE_CHECKING:
    from django.http import HttpRequest


from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
)
from django.shortcuts import redirect, render

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.views.sboms_table import SbomsTableView  # noqa: F401
from sbomify.apps.teams.branding import build_branding_context

logger = logging.getLogger(__name__)


def sbom_details_public(request: HttpRequest, sbom_id: str) -> HttpResponse:
    try:
        sbom: SBOM = SBOM.objects.get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return error_response(request, HttpResponseNotFound("SBOM not found"))

    if not sbom.public_access_allowed:
        return error_response(request, HttpResponseNotFound("SBOM not found"))

    brand = build_branding_context(sbom.component.team)

    return render(
        request,
        "sboms/sbom_details_public.html.j2",
        {
            "sbom": sbom,
            "brand": brand,
            "team_billing_plan": getattr(sbom.component.team, "billing_plan", "community"),
        },
    )


@login_required
def sbom_details_private(request: HttpRequest, sbom_id: str) -> HttpResponse:
    try:
        sbom: SBOM = SBOM.objects.get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return error_response(request, HttpResponseNotFound("SBOM not found"))

    if not verify_item_access(request, sbom, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    return render(
        request,
        "sboms/sbom_details_private.html.j2",
        {
            "sbom": sbom,
            "APP_BASE_URL": settings.APP_BASE_URL,
            "team_billing_plan": getattr(sbom.component.team, "billing_plan", "community"),
        },
    )


@login_required
def sbom_vulnerabilities(request: HttpRequest, sbom_id: str) -> HttpResponse:
    """
    Display vulnerability scan results for a given SBOM.
    """
    try:
        sbom: SBOM = SBOM.objects.get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return error_response(request, HttpResponseNotFound("SBOM not found"))

    if not verify_item_access(request, sbom, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    vulnerabilities_data = None
    scan_timestamp_str = None
    error_message = None
    error_details = None
    is_processing = False
    processing_message = None

    # Initialize default values for template context
    sbom_version_info = None

    try:
        # Fetch the latest vulnerability scan result from PostgreSQL
        from sbomify.apps.vulnerability_scanning.models import VulnerabilityScanResult

        latest_result = VulnerabilityScanResult.objects.filter(sbom=sbom).order_by("-created_at").first()

        if latest_result:
            # Check if this is a processing state for any provider
            scan_metadata = latest_result.scan_metadata or {}
            if scan_metadata.get("processing"):
                is_processing = True
                processing_message = scan_metadata.get("expected_completion", "Processing vulnerability data...")
                scan_timestamp_str = latest_result.created_at.strftime("%B %d, %Y at %I:%M %p %Z")

                # Get SBOM info for display
                sbom_version_info = {
                    "name": sbom.name,
                    "version": sbom.version,
                    "component_name": sbom.component.name,
                    "format": sbom.format,
                    "format_version": sbom.format_version,
                    "source": sbom.source_display,
                }
            else:
                # Normal scan results processing
                # Format timestamp to be human-readable
                scan_timestamp_str = latest_result.created_at.strftime("%B %d, %Y at %I:%M %p %Z")

                # Get SBOM version information for context
                scanned_sbom = latest_result.sbom
                sbom_version_info = {
                    "name": scanned_sbom.name,
                    "version": scanned_sbom.version,
                    "component_name": scanned_sbom.component.name,
                    "format": scanned_sbom.format,
                    "format_version": scanned_sbom.format_version,
                    "source": scanned_sbom.source_display,
                }

                # Transform PostgreSQL data to format expected by template
                findings = latest_result.findings or []

                # Handle both old nested format and new direct array format for backward compatibility
                if isinstance(findings, dict) and "vulnerabilities" in findings:
                    # Old nested format - use as is
                    vulnerabilities_data = findings
                elif isinstance(findings, list):
                    # New standardized direct array format - wrap in expected structure
                    vulnerabilities_data = {
                        "results": [
                            {"source": {"file_path": f"{sbom.name} ({latest_result.provider})"}, "packages": []}
                        ]
                    }

                    # Group vulnerabilities by component/package for display
                    packages_dict = {}
                    for vuln in findings:
                        component = vuln.get("component", {})
                        package_name = component.get("name", "Unknown Package")
                        package_version = component.get("version", "Unknown Version")
                        # Ensure ecosystem is properly extracted and not empty
                        package_ecosystem = component.get("ecosystem", "Unknown")
                        if not package_ecosystem or package_ecosystem in ["Unknown", "unknown"]:
                            # Try to derive from PURL if ecosystem is missing or unknown
                            purl = component.get("purl", "")
                            if purl.startswith("pkg:"):
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

                        # Convert to template-expected format with all needed fields
                        template_vuln = {
                            "id": vuln.get("id", "Unknown"),
                            "aliases": vuln.get("aliases", []),
                            "summary": vuln.get("title") or vuln.get("summary", ""),
                            "details": vuln.get("description", ""),
                            "severity": vuln.get("severity", "medium"),  # Include severity for badge styling
                            "cvss_score": vuln.get("cvss_score"),  # Include CVSS score
                            "references": vuln.get("references", []),  # Include references
                            "source": vuln.get("source", "Unknown"),  # Include data source
                            "affected": vuln.get("affected", []),
                        }

                        packages_dict[package_key]["vulnerabilities"].append(template_vuln)

                    vulnerabilities_data["results"][0]["packages"] = list(packages_dict.values())

            # Check if the scan had errors
            scan_metadata = latest_result.scan_metadata or {}
            if scan_metadata.get("error") or scan_metadata.get("parse_error"):
                # Just pass through the error message from the scan metadata
                error_message = scan_metadata.get("error_message", "An error occurred during vulnerability scanning")

                # Pass through any additional details
                error_details_data = scan_metadata.get("error_details", {})
                if error_details_data and isinstance(error_details_data, dict):
                    # Format the response_data if available for display
                    response_data = error_details_data.get("response_data", {})
                    if response_data:
                        import json

                        error_details = json.dumps(response_data, indent=2)
                    else:
                        error_details = None
                else:
                    error_details = scan_metadata.get("raw_output", None)
        else:
            # No scan results found
            vulnerabilities_data = None

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
            "processing_provider": latest_result.provider.replace("_", " ").title()
            if latest_result and is_processing
            else None,
        },
    )


def sbom_download(request: HttpRequest, sbom_id: str) -> HttpResponse:
    try:
        sbom = SBOM.objects.get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Project not found"))

    if not sbom.public_access_allowed:
        if not verify_item_access(request, sbom, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    if not sbom.sbom_filename:
        return error_response(request, HttpResponseBadRequest("SBOM file not found"))

    s3 = S3Client("SBOMS")
    sbom_data = s3.get_sbom_data(sbom.sbom_filename)
    response = HttpResponse(sbom_data, content_type="application/json")
    response["Content-Disposition"] = "attachment; filename=" + sbom.name

    return response


@login_required
def sbom_upload_cyclonedx(request: HttpRequest) -> HttpResponse:
    # Implementation of sbom_upload_cyclonedx view
    # This is a placeholder and should be replaced with the actual implementation
    return JsonResponse({"detail": "SBOM uploaded successfully", "supplier": None}, status=201)


@login_required
def redirect_sbom_to_component_detailed(request: HttpRequest, sbom_id: str) -> HttpResponse:
    """Redirect old SBOM URLs to new component detailed URLs"""
    try:
        sbom: SBOM = SBOM.objects.get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return error_response(request, HttpResponseNotFound("SBOM not found"))

    # Check access for private view
    if not verify_item_access(request, sbom, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    # Redirect to new component detailed URL
    return redirect("core:component_detailed", component_id=sbom.component_id)


def redirect_sbom_to_component_detailed_public(request: HttpRequest, sbom_id: str) -> HttpResponse:
    """Redirect old public SBOM URLs to new component detailed public URLs"""
    try:
        sbom: SBOM = SBOM.objects.get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return error_response(request, HttpResponseNotFound("SBOM not found"))

    # Check public access
    if not sbom.public_access_allowed:
        return error_response(request, HttpResponseNotFound("SBOM not found"))

    # Redirect to new component detailed public URL
    return redirect("core:component_detailed_public", component_id=sbom.component_id)
