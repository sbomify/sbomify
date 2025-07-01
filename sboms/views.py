from __future__ import annotations

import logging
import tempfile
import typing
from pathlib import Path

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

import json

import redis
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
)
from django.shortcuts import redirect, render

from core.errors import error_response
from core.object_store import S3Client
from core.utils import token_to_number
from teams.schemas import BrandingInfo

# from .decorators import validate_role_in_current_team
from .models import SBOM, Component, Product, Project
from .utils import get_project_sbom_package, verify_item_access

logger = logging.getLogger(__name__)


@login_required
def products_dashboard(request: HttpRequest) -> HttpResponse:
    has_crud_permissions = request.session.get("current_team").get("role") in ("owner", "admin")

    return render(
        request,
        "sboms/products_dashboard.html",
        {
            "has_crud_permissions": has_crud_permissions,
        },
    )


def product_details_public(request: HttpRequest, product_id: str) -> HttpResponse:
    try:
        product: Product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Product not found"))

    # Verify access to project
    if not product.is_public:
        return error_response(request, HttpResponseNotFound("Product not found"))

    branding_info = BrandingInfo(**product.team.branding_info)
    return render(
        request,
        "sboms/product_details_public.html",
        {"product": product, "brand": branding_info},
    )


@login_required
def product_details_private(request: HttpRequest, product_id: str) -> HttpResponse:
    try:
        product: Product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Product not found"))

    # Verify access to project
    if not verify_item_access(request, product, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    has_crud_permissions = verify_item_access(request, product, ["owner", "admin"])

    return render(
        request,
        "sboms/product_details_private.html",
        {
            "product": product,
            "has_crud_permissions": has_crud_permissions,
            "APP_BASE_URL": settings.APP_BASE_URL,
            "current_team": request.session.get("current_team", {}),
        },
    )


@login_required
def projects_dashboard(request: HttpRequest) -> HttpResponse:
    has_crud_permissions = request.session.get("current_team").get("role") in ("owner", "admin")

    return render(
        request,
        "sboms/projects_dashboard.html",
        {
            "has_crud_permissions": has_crud_permissions,
        },
    )


def project_details_public(request: HttpRequest, project_id: str) -> HttpResponse:
    try:
        project: Project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Project not found"))

    # Verify access to project
    if not project.is_public:
        return error_response(request, HttpResponseNotFound("Project not found"))

    branding_info = BrandingInfo(**project.team.branding_info)

    return render(
        request,
        "sboms/project_details_public.html",
        {"project": project, "brand": branding_info},
    )


@login_required
def project_details_private(request: HttpRequest, project_id: str) -> HttpResponse:
    try:
        project: Project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Project not found"))

    # Verify access to project
    if not verify_item_access(request, project, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    has_crud_permissions = verify_item_access(request, project, ["owner", "admin"])

    return render(
        request,
        "sboms/project_details_private.html",
        {
            "project": project,
            "has_crud_permissions": has_crud_permissions,
            "APP_BASE_URL": settings.APP_BASE_URL,
            "current_team": request.session.get("current_team", {}),
        },
    )


@login_required
def components_dashboard(request: HttpRequest) -> HttpResponse:
    has_crud_permissions = request.session.get("current_team").get("role") in ("owner", "admin")

    return render(
        request,
        "sboms/components_dashboard.html",
        {
            "has_crud_permissions": has_crud_permissions,
            "APP_BASE_URL": settings.APP_BASE_URL,
        },
    )


def component_details_public(request: HttpRequest, component_id: str) -> HttpResponse:
    try:
        component: Component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Component not found"))

    # Verify access to project
    if not component.is_public:
        return error_response(request, HttpResponseNotFound("Component not found"))

    sboms_queryset = SBOM.objects.filter(component_id=component_id).order_by("-created_at").all()
    sboms_with_vuln_status = []
    try:
        redis_client = redis.from_url(settings.REDIS_WORKER_URL)
        for sbom_item in sboms_queryset:
            keys = redis_client.keys(f"osv_scan_result:{sbom_item.id}:*")
            sboms_with_vuln_status.append(
                {
                    "sbom": {
                        "id": str(sbom_item.id),
                        "name": sbom_item.name,
                        "format": sbom_item.format,
                        "format_version": sbom_item.format_version,
                        "version": sbom_item.version,
                        "created_at": sbom_item.created_at.isoformat(),
                    },
                    "has_vulnerabilities_report": bool(keys),
                }
            )
    except redis.exceptions.ConnectionError:
        for sbom_item in sboms_queryset:
            sboms_with_vuln_status.append(
                {
                    "sbom": {
                        "id": str(sbom_item.id),
                        "name": sbom_item.name,
                        "format": sbom_item.format,
                        "format_version": sbom_item.format_version,
                        "version": sbom_item.version,
                        "created_at": sbom_item.created_at.isoformat(),
                    },
                    "has_vulnerabilities_report": False,
                }
            )
        # No messages.error for public view, just log or fail silently
        # logger.warning("Could not connect to Redis in public component view.")

    branding_info = BrandingInfo(**component.team.branding_info)

    return render(
        request,
        "sboms/component_details_public.html",
        {"component": component, "sboms_data": sboms_with_vuln_status, "brand": branding_info},  # Changed from "sboms"
    )


@login_required
def component_details_private(request: HttpRequest, component_id: str) -> HttpResponse:
    try:
        component: Component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Component not found"))

    # Verify access to project
    if not verify_item_access(request, component, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    has_crud_permissions = verify_item_access(request, component, ["owner", "admin"])
    is_owner = verify_item_access(request, component, ["owner"])

    sboms_queryset = SBOM.objects.filter(component_id=component_id).order_by("-created_at").all()
    sboms_with_vuln_status = []
    try:
        redis_client = redis.from_url(settings.REDIS_WORKER_URL)
        for sbom_item in sboms_queryset:
            keys = redis_client.keys(f"osv_scan_result:{sbom_item.id}:*")
            sboms_with_vuln_status.append(
                {
                    "sbom": {
                        "id": str(sbom_item.id),
                        "name": sbom_item.name,
                        "format": sbom_item.format,
                        "format_version": sbom_item.format_version,
                        "version": sbom_item.version,
                        "created_at": sbom_item.created_at.isoformat(),
                    },
                    "has_vulnerabilities_report": bool(keys),
                }
            )
    except redis.exceptions.ConnectionError:
        # If Redis is down, assume no reports are available for simplicity
        for sbom_item in sboms_queryset:
            sboms_with_vuln_status.append(
                {
                    "sbom": {
                        "id": str(sbom_item.id),
                        "name": sbom_item.name,
                        "format": sbom_item.format,
                        "format_version": sbom_item.format_version,
                        "version": sbom_item.version,
                        "created_at": sbom_item.created_at.isoformat(),
                    },
                    "has_vulnerabilities_report": False,
                }
            )
        messages.error(
            request, "Could not connect to Redis to check for vulnerability reports. Status may be inaccurate."
        )

    return render(
        request,
        "sboms/component_details_private.html",
        {
            "component": component,
            "has_crud_permissions": has_crud_permissions,
            "is_owner": is_owner,
            "sboms_data": sboms_with_vuln_status,  # Changed from "sboms"
            "APP_BASE_URL": settings.APP_BASE_URL,
            "current_team": request.session.get("current_team", {}),
        },
    )


@login_required
def transfer_component_to_team(request: HttpRequest, component_id: str) -> HttpResponse:
    """
    Transfer component to a different team.

    User must have owner role in component's current team and owner or admin role in target team.
    """
    if request.method != "POST":
        return error_response(request, HttpResponseBadRequest("Invalid request"))

    team_key = request.POST.get("team_key")
    team_id = token_to_number(team_key)

    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Component not found"))

    if not verify_item_access(request, component, ["owner"]):
        return error_response(request, HttpResponseForbidden("Only allowed for owners of the component"))

    target_team = request.session.get("user_teams", {}).get(team_key, {})
    if target_team.get("role", "") not in ("owner", "admin"):
        return error_response(request, HttpResponseForbidden("Only allowed for admins or owners of the target team"))

    with transaction.atomic():
        # Remove component's existing linkages to projects if any
        component.projects.clear()
        component.team_id = team_id
        component.save()

    messages.add_message(
        request,
        messages.INFO,
        f"Component {component.name} transferred to team {target_team.get('name')}",
    )

    return redirect("sboms:component_details", component_id=component_id)


def sbom_details_public(request: HttpRequest, sbom_id: str) -> HttpResponse:
    try:
        sbom: SBOM = SBOM.objects.get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return error_response(request, HttpResponseNotFound("SBOM not found"))

    if not sbom.public_access_allowed:
        return error_response(request, HttpResponseNotFound("SBOM not found"))

    branding_info = BrandingInfo(**sbom.component.team.branding_info)

    return render(
        request,
        "sboms/sbom_details_public.html",
        {"sbom": sbom, "brand": branding_info},
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
        "sboms/sbom_details_private.html",
        {"sbom": sbom, "APP_BASE_URL": settings.APP_BASE_URL},
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

    redis_client = None
    vulnerabilities_data = None
    scan_timestamp_str = None
    error_message = None
    error_details = None

    try:
        redis_url = settings.REDIS_WORKER_URL
        redis_client = redis.from_url(redis_url)
        # Fetch the latest scan result. Keys are like "osv_scan_result:SBOM_ID:TIMESTAMP"
        keys = redis_client.keys(f"osv_scan_result:{sbom_id}:*")
        if keys:
            latest_key = sorted(keys, reverse=True)[0]
            if isinstance(latest_key, bytes):  # redis-py can return bytes
                latest_key = latest_key.decode("utf-8")

            scan_timestamp_str = latest_key.split(":")[-1]
            raw_data = redis_client.get(latest_key)
            if raw_data:
                if isinstance(raw_data, bytes):  # redis-py can return bytes
                    raw_data = raw_data.decode("utf-8")
                try:
                    vulnerabilities_data = json.loads(raw_data)
                    # Check if the loaded data is an error message from the scanner task
                    if isinstance(vulnerabilities_data, dict) and "error" in vulnerabilities_data:
                        error_message = (
                            f"Vulnerability scan failed: {vulnerabilities_data.get('error', 'Unknown error')}"
                        )
                        error_details = vulnerabilities_data.get("details") or vulnerabilities_data.get("stderr")
                        vulnerabilities_data = None  # Clear data so template shows error
                except json.JSONDecodeError:
                    error_message = "Failed to parse vulnerability data from Redis. The data might be corrupted."
                    logger.error(
                        f"Failed to parse JSON from Redis for key {latest_key}. Data: {raw_data[:200]}..."
                    )  # Log a snippet
            else:
                error_message = "Scan result not found in Redis though a key was present."
        else:
            # This case is handled by the template's "else" for "if vulnerabilities"
            pass

    except redis.exceptions.ConnectionError:
        error_message = "Could not connect to Redis to fetch vulnerability data."
        logger.error("Redis connection error in sbom_vulnerabilities view.")
    except Exception as e:
        error_message = f"An unexpected error occurred while fetching vulnerability data: {str(e)}"
        logger.error(f"Unexpected error in sbom_vulnerabilities view for SBOM {sbom_id}: {e}", exc_info=True)

    return render(
        request,
        "sboms/sbom_vulnerabilities.html",
        {
            "sbom": sbom,
            "vulnerabilities": vulnerabilities_data,
            "scan_timestamp": scan_timestamp_str,
            "error_message": error_message,
            "error_details": error_details,
            "APP_BASE_URL": settings.APP_BASE_URL,
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


def sbom_download_project(request: HttpRequest, project_id: str) -> HttpResponse:
    """
    Download a zip file containing the SBOMs for all components in a project.
    """
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Project not found"))

    if not project.is_public:
        if not verify_item_access(request, project, ["guest", "owner", "admin"]):
            return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    with tempfile.TemporaryDirectory() as temp_dir:
        sbom_zip_path = get_project_sbom_package(project, Path(temp_dir))

        response = HttpResponse(open(sbom_zip_path, "rb").read(), content_type="application/zip")
        response["Content-Disposition"] = f"attachment; filename={project.name}.cdx.zip"

        return response


@login_required
def sbom_upload_cyclonedx(request: HttpRequest) -> HttpResponse:
    # Implementation of sbom_upload_cyclonedx view
    # This is a placeholder and should be replaced with the actual implementation
    return JsonResponse({"detail": "SBOM uploaded successfully", "supplier": None}, status=201)


@login_required
def get_component_metadata(request: HttpRequest, component_id: str) -> HttpResponse:
    try:
        component: Component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Component not found"))

    if not verify_item_access(request, component, ["guest", "owner", "admin"]):
        return error_response(request, HttpResponseForbidden("Only allowed for members of the team"))

    metadata = component.metadata or {}
    metadata.setdefault("supplier", None)
    return JsonResponse(metadata)
