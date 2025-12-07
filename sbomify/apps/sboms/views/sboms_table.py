from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.apis import get_component, list_component_sboms
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.sboms.apis import delete_sbom
from sbomify.apps.sboms.forms import SbomDeleteForm
from sbomify.apps.teams.apis import get_team


class SbomsTableView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, component_id: str, is_public_view: bool) -> HttpResponse:
        status_code, component = get_component(request, component_id)
        if status_code != 200:
            return htmx_error_response(component.get("detail", "Unknown error"))

        status_code, sboms = list_component_sboms(request, component_id, page=1, page_size=-1)
        if status_code != 200:
            return htmx_error_response(sboms.get("detail", "Failed to load SBOMs"))

        team_key = number_to_random_token(component.get("team_id"))
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Failed to load team"))

        context = {
            "component_id": component_id,
            "sboms": sboms.get("items"),
            "is_public_view": is_public_view,
            "has_crud_permissions": component.get("has_crud_permissions", False) if not is_public_view else False,
            "team_billing_plan": team.billing_plan,
            "team_key": team_key,
            "delete_form": SbomDeleteForm(),
        }

        return render(request, "sboms/sboms_table.html.j2", context)

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.POST.get("_method") == "DELETE":
            return self._delete(request)

        return htmx_error_response("Invalid request")

    def _delete(self, request: HttpRequest) -> HttpResponse:
        form = SbomDeleteForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        sbom_id = form.cleaned_data["sbom_id"]

        status_code, result = delete_sbom(request, sbom_id)
        if status_code != 204:
            return htmx_error_response(result.get("detail", "Failed to delete SBOM"))

        return htmx_success_response("SBOM deleted successfully", triggers={"refreshSbomsTable": True})
