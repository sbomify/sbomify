import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.views import View

from sbomify.apps.core.apis import patch_component, patch_product, patch_project
from sbomify.apps.core.forms import TogglePublicStatusForm
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.schemas import ComponentPatchSchema, ProductPatchSchema, ProjectPatchSchema

log = logging.getLogger(__name__)


PATCH_API_MAP = {
    "component": (patch_component, ComponentPatchSchema),
    "product": (patch_product, ProductPatchSchema),
    "project": (patch_project, ProjectPatchSchema),
}


class TogglePublicStatusView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, item_type: str, item_id: str) -> HttpResponse:
        form = TogglePublicStatusForm(request.POST)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        api_func, schema_class = PATCH_API_MAP[item_type]

        status_code, result = api_func(request, item_id, schema_class(is_public=form.cleaned_data["is_public"]))
        if status_code != 200:
            return htmx_error_response(result.get("detail", f"Failed to update {item_type}"), content={})

        return htmx_success_response(
            f"{item_type.capitalize()} is now {'public' if result.get('is_public') else 'private'}",
            content={"is_public": result.get("is_public")},
        )
