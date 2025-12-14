import logging

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.sboms.models import SBOM

logger = logging.getLogger(__name__)


class SbomDownloadView(View):
    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        try:
            sbom = SBOM.objects.get(pk=sbom_id)
        except SBOM.DoesNotExist:
            return error_response(request, HttpResponseNotFound("SBOM not found"))

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
