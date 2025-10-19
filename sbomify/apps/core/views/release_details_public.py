from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Release
from sbomify.apps.teams.schemas import BrandingInfo


class ReleaseDetailsPublicView(View):
    def get(self, request: HttpRequest, product_id: str, release_id: str) -> HttpResponse:
        from sbomify.apps.core.apis import get_release

        try:
            release = Release.objects.get(pk=release_id)
        except Release.DoesNotExist:
            return error_response(request, HttpResponseNotFound("Release not found"))

        status_code, release_data = get_release(request, release_id)
        if status_code != 200:
            return error_response(request, HttpResponseNotFound("Release not found"))

        release = Release.objects.get(pk=release_id)

        artifacts_data = release_data.get("artifacts", [])
        has_downloadable_content = release_data.get("has_sboms", False)

        branding_info = BrandingInfo(**release.product.team.branding_info)
        return render(
            request,
            "core/release_details_public.html.j2",
            {
                "product": release.product,
                "release": release,
                "brand": branding_info,
                "has_downloadable_content": has_downloadable_content,
                "artifacts_data": artifacts_data,
            },
        )
