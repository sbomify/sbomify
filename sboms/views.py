from __future__ import annotations

import logging
import typing

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

import json

import redis
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
)
from django.shortcuts import render

from core.errors import error_response
from core.object_store import S3Client
from core.utils import verify_item_access
from teams.schemas import BrandingInfo

# from .decorators import validate_role_in_current_team
from .models import SBOM

logger = logging.getLogger(__name__)


# Product/Project/Component views moved to core app


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
        "sboms/sbom_details_public.html.j2",
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
        "sboms/sbom_details_private.html.j2",
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
        "sboms/sbom_vulnerabilities.html.j2",
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


# Product/Project SBOM downloads moved to core app


@login_required
def sbom_upload_cyclonedx(request: HttpRequest) -> HttpResponse:
    # Implementation of sbom_upload_cyclonedx view
    # This is a placeholder and should be replaced with the actual implementation
    return JsonResponse({"detail": "SBOM uploaded successfully", "supplier": None}, status=201)


# Component metadata view moved to core app
