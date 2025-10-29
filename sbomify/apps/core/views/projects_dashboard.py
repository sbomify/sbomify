from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.apis import create_project, list_projects
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.schemas import ProjectCreateSchema


class ProjectsDashboardView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        status_code, projects = list_projects(request, page=1, page_size=-1)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=projects.get("detail", "Unknown error"))
            )

        current_team = request.session.get("current_team")
        has_crud_permissions = current_team.get("role") in ["owner", "admin"] if current_team else False

        return render(
            request,
            "core/projects_dashboard.html.j2",
            {
                "current_team": current_team,
                "has_crud_permissions": has_crud_permissions,
                "projects": projects.items,
            },
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        name = request.POST.get("name", "").strip()

        payload = ProjectCreateSchema(
            name=name,
        )

        status_code, response_data = create_project(request, payload)
        if status_code == 201:
            messages.success(request, f'Project "{name}" created successfully!')
        else:
            error_detail = response_data.get("detail", "An error occurred while creating the project")
            messages.error(request, error_detail)

        return redirect("core:projects_dashboard")
