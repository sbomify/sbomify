from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.documents.services.documents_table import (
    build_documents_table_context,
    delete_document_from_request,
    update_document_from_request,
)


class DocumentsTableView(View):
    def dispatch(self, request, *args, **kwargs):
        # Get is_public_view from kwargs (set by URL configuration)
        is_public_view = kwargs.get("is_public_view", False)

        # For public views, allow unauthenticated access
        if is_public_view:
            return super().dispatch(request, *args, **kwargs)

        # For private views, require login
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            from django.urls import reverse

            login_url = reverse("core:keycloak_login")
            return redirect_to_login(request.get_full_path(), login_url)

        # Block guest members from private views
        if request.user.is_authenticated:
            current_team = request.session.get("current_team", {})
            team_key = current_team.get("key")
            if team_key:
                from sbomify.apps.teams.models import Member, Team

                try:
                    team = Team.objects.get(key=team_key)
                    Member.objects.get(user=request.user, team=team, role="guest")
                    from django.shortcuts import redirect

                    return redirect("core:workspace_public", workspace_key=team_key)
                except (Member.DoesNotExist, Team.DoesNotExist):
                    pass

        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, component_id: str, is_public_view: bool) -> HttpResponse:
        result = build_documents_table_context(request, component_id, is_public_view)
        if not result.ok:
            return htmx_error_response(result.error or "Unknown error")

        return render(request, "documents/documents_table.html.j2", result.value)

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        # POST operations require authentication
        if not request.user.is_authenticated:
            return htmx_error_response("Authentication required")

        # Block guest members from modifying documents (even on public views)
        current_team = request.session.get("current_team", {})
        team_key = current_team.get("key")
        if team_key:
            from sbomify.apps.teams.models import Member, Team

            try:
                team = Team.objects.get(key=team_key)
                Member.objects.get(user=request.user, team=team, role="guest")
                return htmx_error_response("Guest members cannot modify documents")
            except (Member.DoesNotExist, Team.DoesNotExist):
                pass

        if request.POST.get("_method") == "DELETE":
            return self._delete(request)
        elif request.POST.get("_method") == "PATCH":
            return self._patch(request)

        return htmx_error_response("Invalid request")

    def _delete(self, request: HttpRequest) -> HttpResponse:
        result = delete_document_from_request(request)
        if not result.ok:
            return htmx_error_response(result.error or "Failed to delete document")

        return htmx_success_response("Document deleted successfully", triggers={"refreshDocumentsTable": True})

    def _patch(self, request: HttpRequest) -> HttpResponse:
        result = update_document_from_request(request)
        if not result.ok:
            return htmx_error_response(result.error or "Failed to update document")

        return htmx_success_response("Document updated successfully", triggers={"refreshDocumentsTable": True})
