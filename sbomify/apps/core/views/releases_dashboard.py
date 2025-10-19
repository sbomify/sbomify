from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View


class ReleasesDashboardView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        from sbomify.apps.core.apis import list_all_releases

        current_team = request.session.get("current_team")
        has_crud_permissions = current_team and current_team.get("role") in ("owner", "admin")

        status_code, response_data = list_all_releases(request, product_id=None, page=1, page_size=-1)
        releases = response_data.get("items", []) if status_code == 200 else []

        return render(
            request,
            "core/releases_dashboard.html.j2",
            {
                "has_crud_permissions": has_crud_permissions,
                "APP_BASE_URL": settings.APP_BASE_URL,
                "releases": releases,
            },
        )
