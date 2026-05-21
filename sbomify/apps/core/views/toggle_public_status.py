from __future__ import annotations

import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.views import View

from sbomify.apps.core.apis import patch_component, patch_product
from sbomify.apps.core.forms import TogglePublicStatusForm
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.posthog_service import capture_for_request
from sbomify.apps.core.schemas import ComponentPatchSchema, ProductPatchSchema
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin

log = logging.getLogger(__name__)


PATCH_API_MAP = {
    "component": (patch_component, ComponentPatchSchema),
    "product": (patch_product, ProductPatchSchema),
}


class TogglePublicStatusView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    def post(self, request: HttpRequest, item_type: str, item_id: str) -> HttpResponse:
        # For components, use visibility; for products, use is_public
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
                schema = ComponentPatchSchema(visibility=visibility_enum)  # type: ignore[call-arg]
            except Exception as e:
                log.error(f"Failed to create ComponentPatchSchema: {e}")
                return htmx_error_response(f"Invalid visibility value: {e}", content={})

            status_code, result = api_func(request, item_id, schema)  # type: ignore[operator]
            if status_code != 200:
                error_detail = result.get("detail", f"Failed to update {item_type}")
                errors = result.get("errors", {})
                if errors:
                    error_detail = f"{error_detail}: {errors}"
                log.error(f"Failed to update component {item_id}: {error_detail}, errors: {errors}")
                return htmx_error_response(error_detail, content={})

            # ``visibility`` is the validated lowercase string from request.POST;
            # ``result.get("visibility")`` may be a ``ComponentVisibility`` enum
            # (depending on the API response shape) which has no ``.capitalize()``
            # and would stringify to "ComponentVisibility.PUBLIC". Derive the
            # message text from the local string, and serialize the enum to
            # its ``.value`` for the HTMX payload so callers see a plain string.
            self._capture_toggle(request, item_type, item_id, visibility)
            result_visibility = result.get("visibility")
            result_visibility_str = (
                getattr(result_visibility, "value", result_visibility) if result_visibility else "private"
            )
            return htmx_success_response(
                f"{item_type.capitalize()} visibility is now {visibility.capitalize()}",
                content={"visibility": result_visibility_str},
            )
        else:
            # Products use is_public
            form = TogglePublicStatusForm(request.POST)
            if not form.is_valid():
                return htmx_error_response(form.errors.as_text())

            api_func, schema_class = PATCH_API_MAP[item_type]

            status_code, result = api_func(request, item_id, schema_class(is_public=form.cleaned_data["is_public"]))  # type: ignore[operator]
            if status_code != 200:
                return htmx_error_response(result.get("detail", f"Failed to update {item_type}"), content={})

            new_visibility = "public" if result.get("is_public") else "private"
            self._capture_toggle(request, item_type, item_id, new_visibility)
            return htmx_success_response(
                f"{item_type.capitalize()} is now {'public' if result.get('is_public') else 'private'}",
                content={"is_public": result.get("is_public")},
            )

    @staticmethod
    def _capture_toggle(request: HttpRequest, item_type: str, item_id: str, new_visibility: str) -> None:
        # Empty team_key here means the session is missing the
        # ``current_team`` shape; ``capture_for_request`` will skip the
        # event entirely rather than mis-attribute it to a user PK (see
        # the empty-string branch in posthog_service.capture_for_request).
        team_key = (request.session.get("current_team") or {}).get("key", "")
        # Deferred via ``on_commit`` so a rollback in the surrounding
        # ``patch_*`` flow doesn't ship a ghost visibility toggle event.
        transaction.on_commit(
            lambda: capture_for_request(
                request,
                "item:visibility_toggled",
                {"item_type": item_type, "item_id": item_id, "new_visibility": new_visibility},
                team_key=team_key,
            )
        )
