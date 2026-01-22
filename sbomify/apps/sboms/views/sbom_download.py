import logging

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.services.access_control import check_component_access
from sbomify.apps.sboms.models import SBOM

logger = logging.getLogger(__name__)


class SbomDownloadView(View):
    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        try:
            sbom = SBOM.objects.get(pk=sbom_id)
        except SBOM.DoesNotExist:
            return error_response(request, HttpResponseNotFound("SBOM not found"))

        # Check access permissions using centralized access control
        component = sbom.component
        access_result = check_component_access(request, component)

        if not access_result.has_access:
            # Check if this is a request from a public page (via query param or session)
            # Using query param is more reliable than HTTP_REFERER which can be spoofed/absent
            is_from_public_page = request.GET.get("from_public") == "true" or request.session.get(
                "viewing_public_component"
            ) == str(component.id)

            # Provide helpful error message for gated components
            if component.visibility == component.Visibility.GATED:
                if is_from_public_page:
                    # Return a simple HTML page with message and redirect back
                    from django.shortcuts import render
                    from django.urls import reverse

                    team = component.team
                    error_message = (
                        "Please request access to download this SBOM."
                        if not request.user.is_authenticated
                        else "Your access request is pending approval or has been rejected."
                    )
                    request_access_url = (
                        reverse("documents:request_access", kwargs={"team_key": team.key}) if team else None
                    )

                    # Get component detail page URL instead of referrer to avoid loops
                    component_detail_url = reverse(
                        "core:component_details_public",
                        kwargs={"component_id": component.id},
                    )

                    return render(
                        request,
                        "core/access_denied_message.html.j2",
                        {
                            "error_message": error_message,
                            "request_access_url": request_access_url,
                            "back_url": component_detail_url,
                            "item_type": "SBOM",
                        },
                        status=403,
                    )

                if not request.user.is_authenticated:
                    return error_response(
                        request,
                        HttpResponseForbidden("Access denied. Please request access to download this SBOM."),
                    )
                else:
                    return error_response(
                        request,
                        HttpResponseForbidden(
                            "Access denied. Your access request is pending approval or has been rejected."
                        ),
                    )
            return error_response(request, HttpResponseForbidden("Access denied"))

        if not sbom.sbom_filename:
            return error_response(request, HttpResponseBadRequest("SBOM file not found"))

        try:
            s3 = S3Client("SBOMS")
            sbom_data = s3.get_sbom_data(sbom.sbom_filename)

            if not sbom_data:
                logger.warning(f"SBOM file {sbom.sbom_filename} returned empty data from S3")
                return error_response(request, HttpResponseNotFound("SBOM file not found in storage"))

            response = HttpResponse(sbom_data, content_type="application/json")
            response["Content-Disposition"] = "attachment; filename=" + sbom.name
            return response

        except Exception as e:
            from botocore.exceptions import ClientError

            # Check if it's a NoSuchKey error (file doesn't exist in S3)
            if isinstance(e, ClientError):
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "NoSuchKey":
                    logger.error(
                        f"SBOM file {sbom.sbom_filename} not found in S3 for SBOM {sbom_id}. "
                        f"The database record exists but the file is missing."
                    )
                    return error_response(
                        request, HttpResponseNotFound("SBOM file not found in storage. The file may have been deleted.")
                    )

            # For other errors, log and return generic error
            logger.exception(f"Error downloading SBOM {sbom_id}: {e}")
            return error_response(request, HttpResponse(status=500, content="Error retrieving SBOM file"))
