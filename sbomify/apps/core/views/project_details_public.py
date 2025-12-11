from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_project
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.url_utils import add_custom_domain_to_context, resolve_project_identifier
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Team


class ProjectDetailsPublicView(View):
    def get(self, request: HttpRequest, project_id: str) -> HttpResponse:
        # Resolve project by slug (on custom domains) or ID (on main app)
        project_obj = resolve_project_identifier(request, project_id)
        if not project_obj:
            return error_response(request, HttpResponseNotFound("Project not found"))

        # Use the resolved project's ID for API calls
        resolved_id = project_obj.id

        status_code, project = get_project(request, resolved_id)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=project.get("detail", "Unknown error"))
            )

        has_downloadable_content = SBOM.objects.filter(component__projects=project["id"]).exists()
        team = Team.objects.filter(pk=project.get("team_id")).first()

        brand = build_branding_context(team)

        context = {
            "project": project,
            "brand": brand,
            "has_downloadable_content": has_downloadable_content,
        }
        add_custom_domain_to_context(request, context, team)

        return render(request, "core/project_details_public.html.j2", context)
