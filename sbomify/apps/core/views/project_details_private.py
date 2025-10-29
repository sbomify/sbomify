from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_dashboard_summary, get_project
from sbomify.apps.core.errors import error_response


class ProjectDetailsPrivateView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, project_id: str) -> HttpResponse:
        status_code, project = get_project(request, project_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=project.get("detail", "Unknown error"))
            )

        status_code, dashboard_summary = get_dashboard_summary(request, product_id=None, project_id=project_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=dashboard_summary.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team", {})

        return render(
            request,
            "core/project_details_private.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "current_team": current_team,
                "dashboard_summary": dashboard_summary,
                "project": project,
            },
        )
