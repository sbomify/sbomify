from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.apis import create_component
from sbomify.apps.core.authz import MANAGE
from sbomify.apps.core.forms import ComponentCreateForm
from sbomify.apps.core.schemas import ComponentCreateSchema
from sbomify.apps.core.views.products_dashboard import InventoryView, ProductsTableView
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin
from sbomify.apps.teams.queries import get_member_role_by_key


def _create_component(request: HttpRequest) -> HttpResponse:
    """Validate before calling the API and retain the form on any error."""
    form = ComponentCreateForm(request.POST)
    if form.is_valid():
        status_code, response = create_component(request, ComponentCreateSchema.model_validate(form.cleaned_data))
        if status_code == 201:
            messages.success(request, "Component created")
            return redirect("core:component_details", component_id=response["id"])
        form.add_error(None, response.get("detail", "Unable to create the component."))
    return render(request, "core/component_new.html.j2", {"form": form, "type_options": COMPONENT_TYPE_OPTIONS})


class ComponentsDashboardView(InventoryView):
    inventory_kind = "components"

    def post(self, request: HttpRequest) -> HttpResponse:
        # Kept so anything still posting the create form at the list URL keeps
        # working; the form itself now lives at component_new.
        return _create_component(request)


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
            {"form": ComponentCreateForm(), "type_options": COMPONENT_TYPE_OPTIONS},
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        return _create_component(request)


class ComponentsTableView(ProductsTableView):
    inventory_kind = "components"
