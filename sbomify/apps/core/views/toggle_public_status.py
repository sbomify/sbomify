import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.views import View

from sbomify.apps.core.apis import patch_component, patch_product, patch_project
from sbomify.apps.core.forms import TogglePublicStatusForm
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.schemas import ComponentPatchSchema, ProductPatchSchema, ProjectPatchSchema
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin

log = logging.getLogger(__name__)


PATCH_API_MAP = {
    "component": (patch_component, ComponentPatchSchema),
    "product": (patch_product, ProductPatchSchema),
    "project": (patch_project, ProjectPatchSchema),
}


class TogglePublicStatusView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def post(self, request: HttpRequest, item_type: str, item_id: str) -> HttpResponse:
        # For components, use visibility; for products/projects, use is_public
        if item_type == "component":
            # Handle visibility field for components
            visibility = request.POST.get("visibility", "").strip().lower()
            if visibility not in ("public", "private", "gated"):
                return htmx_error_response("Invalid visibility value. Must be 'public', 'private', or 'gated'.")

            from sbomify.apps.core.schemas import ComponentPatchSchema, ComponentVisibility

            # Convert string to enum
            try:
                visibility_enum = ComponentVisibility(visibility)
            except ValueError:
                return htmx_error_response("Invalid visibility value. Must be 'public', 'private', or 'gated'.")

            api_func, _ = PATCH_API_MAP[item_type]
            try:
                schema = ComponentPatchSchema(visibility=visibility_enum)
            except Exception as e:
                log.error(f"Failed to create ComponentPatchSchema: {e}")
                return htmx_error_response(f"Invalid visibility value: {e}", content={})

            status_code, result = api_func(request, item_id, schema)
            if status_code != 200:
                error_detail = result.get("detail", f"Failed to update {item_type}")
                errors = result.get("errors", {})
                if errors:
                    error_detail = f"{error_detail}: {errors}"
                log.error(f"Failed to update component {item_id}: {error_detail}, errors: {errors}")
                return htmx_error_response(error_detail, content={})

            visibility = result.get("visibility")
            visibility_text = visibility.capitalize() if visibility else "private"
            return htmx_success_response(
                f"{item_type.capitalize()} visibility is now {visibility_text}",
                content={"visibility": visibility},
            )
        else:
            # Products and Projects use is_public
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
