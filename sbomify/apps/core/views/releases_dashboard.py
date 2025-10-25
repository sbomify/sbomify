from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import list_all_releases
from sbomify.apps.core.errors import error_response


class ReleasesDashboardView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        status_code, releases = list_all_releases(request, product_id=None, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=releases.get("detail", "Unknown error"))
            )

        return render(
            request,
            "core/releases_dashboard.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "releases": releases.items,
            },
        )
