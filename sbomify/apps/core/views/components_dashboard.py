from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.apis import create_component
from sbomify.apps.core.authz import MANAGE
from sbomify.apps.core.schemas import ComponentCreateSchema
from sbomify.apps.core.views.products_dashboard import InventoryView, ProductsTableView
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.teams.queries import get_member_role_by_key


def _create_component(request: HttpRequest, *, on_error: str) -> HttpResponse:
    """Create a component from a posted form, returning to `on_error` if it fails."""
    name = request.POST.get("name", "").strip()
    component_type = request.POST.get("component_type", "bom")
    is_global = request.POST.get("is_global") == "on"

    payload = ComponentCreateSchema(
        name=name,
        component_type=component_type,  # type: ignore[arg-type]
        metadata={},
        is_global=is_global,
    )

    status_code, response = create_component(request, payload)
    if status_code != 201:
        error_detail = response.get("detail", "An error occurred while creating the component")
        messages.error(request, error_detail)
        return redirect(on_error)

    messages.success(request, f'Component "{name}" created successfully!')
    # `create_component` returns the API response dict (see `_build_item_response`),
    # not a model instance, so read the id by key.
    return redirect("core:component_details", component_id=response["id"])


class ComponentsDashboardView(InventoryView):
    inventory_kind = "components"

    def post(self, request: HttpRequest) -> HttpResponse:
        # Kept so anything still posting the create form at the list URL keeps
        # working; the form itself now lives at component_new.
        return _create_component(request, on_error="core:components_dashboard")


# Component type as the New Component form offers it, shaped for
# c-layout.choice-group: the tile wears the icon the type wears elsewhere.
COMPONENT_TYPE_OPTIONS: list[dict[str, str]] = [
    {"value": "bom", "label": "BOM", "icon": "fas fa-file-code"},
    {"value": "document", "label": "Document", "icon": "fas fa-file-lines"},
]


class ComponentCreateView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """The New Component form, as a page, matching the New Advisory flow."""

    def get(self, request: HttpRequest) -> HttpResponse:
        current_team = request.session.get("current_team") or {}
        if get_member_role_by_key(request.user, current_team.get("key")) not in MANAGE:
            raise Http404("Workspace not found")

        return render(
            request,
            "core/component_new.html.j2",
            {"current_team": current_team, "type_options": COMPONENT_TYPE_OPTIONS},
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        return _create_component(request, on_error="core:component_new")


class ComponentsTableView(ProductsTableView):
    inventory_kind = "components"
