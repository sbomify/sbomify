from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_project
from sbomify.apps.core.errors import error_response
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ProjectDetailsPublicView(View):
    def get(self, request: HttpRequest, project_id: str) -> HttpResponse:
        # Check if this is a custom domain request
        is_custom_domain = getattr(request, "is_custom_domain", False)

        # If on custom domain, verify the project belongs to this workspace
        if is_custom_domain and hasattr(request, "custom_domain_team"):
            from sbomify.apps.core.models import Project

            try:
                project_obj = Project.objects.get(id=project_id)
                if project_obj.team != request.custom_domain_team:
                    return error_response(request, HttpResponseNotFound("Project not found"))
            except Project.DoesNotExist:
                return error_response(request, HttpResponseNotFound("Project not found"))

        status_code, project = get_project(request, project_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=project.get("detail", "Unknown error"))
            )

        has_downloadable_content = SBOM.objects.filter(component__projects=project["id"]).exists()
        team = Team.objects.filter(pk=project.get("team_id")).first()

        # Don't redirect - always show public content on whichever domain the user is on
        # Public pages should be accessible on both main domain and custom domain

        brand = build_branding_context(team)

        return render(
            request,
            "core/project_details_public.html.j2",
            {
                "project": project,
                "brand": brand,
                "has_downloadable_content": has_downloadable_content,
                "is_custom_domain": is_custom_domain,
                "custom_domain": team.custom_domain if is_custom_domain else None,
            },
        )
