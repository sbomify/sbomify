from __future__ import annotations

from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.controls.models import Control
from sbomify.apps.controls.services.catalog_service import (
    activate_builtin_catalog,
    deactivate_catalog,
    delete_catalog,
)
from sbomify.apps.controls.services.page_context import build_product_controls, controls_table_context
from sbomify.apps.controls.services.status_service import upsert_status
from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.core.models import User
from sbomify.apps.teams.models import Team
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin, TeamRoleRequiredMixin


def _check_team_key_matches_session(request: HttpRequest, team_key: str) -> bool:
    """Return True if the session's current_team key matches the URL team_key."""
    current_team_key: str = request.session.get("current_team", {}).get("key", "")
    return current_team_key == team_key


class ProductControlsView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Load the same controls tables with product-specific overrides."""

    def get(self, request: HttpRequest, team_key: str, product_id: str) -> HttpResponse:
        result = build_product_controls(request, team_key, product_id)
        if not result.ok:
            return htmx_error_response(result.error or "Unable to load controls")
        return render(request, "controls/components/product_controls_section.html.j2", result.value)


class ControlsCatalogView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Handle activate/deactivate catalog POST actions."""

    allowed_roles = list(ADMINISTER)

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from sbomify.apps.teams.utils import redirect_to_team_settings

        if not _check_team_key_matches_session(request, team_key):
            messages.error(request, "Unauthorized: workspace mismatch")
            return redirect_to_team_settings(team_key, "controls")

        action = request.POST.get("controls_catalog_action", "")

        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return redirect_to_team_settings(team_key, "controls")

        if action == "activate":
            catalog_name = request.POST.get("catalog_name", "soc2-type2")
            if catalog_name == "__custom__":
                # Reactivate an existing imported catalog by ID
                from sbomify.apps.controls.models import ControlCatalog

                catalog_id = request.POST.get("catalog_id", "")
                try:
                    catalog = ControlCatalog.objects.get(id=catalog_id, team=team)
                    catalog.is_active = True
                    catalog.save(update_fields=["is_active", "updated_at"])
                    messages.success(request, f"Activated {catalog.name} with {catalog.controls.count()} controls.")
                except ControlCatalog.DoesNotExist:
                    messages.error(request, "Catalog not found")
            else:
                activate_result = activate_builtin_catalog(team, catalog_name)
                if activate_result.ok and activate_result.value is not None:
                    catalog = activate_result.value
                    ctrl_count = catalog.controls.count()
                    messages.success(request, f"Activated {catalog.name} catalog with {ctrl_count} controls.")
                else:
                    messages.error(request, activate_result.error or "Failed to activate catalog")

        elif action == "deactivate":
            catalog_id = request.POST.get("catalog_id", "")
            if not catalog_id:
                messages.error(request, "No catalog specified")
                return redirect_to_team_settings(team_key, "controls")

            deactivate_result = deactivate_catalog(catalog_id, team)
            if deactivate_result.ok:
                messages.success(request, "Catalog deactivated.")
            else:
                messages.error(request, deactivate_result.error or "Failed to deactivate catalog")

        elif action == "delete":
            catalog_id = request.POST.get("catalog_id", "")
            if not catalog_id:
                messages.error(request, "No catalog specified")
                return redirect_to_team_settings(team_key, "controls")

            delete_result = delete_catalog(catalog_id, team)
            if delete_result.ok:
                messages.success(request, "Catalog deleted permanently.")
            else:
                messages.error(request, delete_result.error or "Failed to delete catalog")
        else:
            messages.error(request, "Invalid action")

        return redirect_to_team_settings(team_key, "controls")


class ControlsStatusView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Handle individual control status update POST (HTMX inline)."""

    allowed_roles = list(ADMINISTER)

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from sbomify.apps.teams.utils import redirect_to_team_settings

        if not _check_team_key_matches_session(request, team_key):
            messages.error(request, "Unauthorized: workspace mismatch")
            return redirect_to_team_settings(team_key, "controls")

        user = cast(User, request.user)
        control_id = request.POST.get("control_id", "")
        status = request.POST.get("status", "")

        if not control_id or not status:
            messages.error(request, "Missing control or status")
            return redirect_to_team_settings(team_key, "controls")

        try:
            control = Control.objects.get(id=control_id, catalog__team__key=team_key)
        except Control.DoesNotExist:
            messages.error(request, "Control not found")
            return redirect_to_team_settings(team_key, "controls")

        upsert_result = upsert_status(control, None, status, user)
        if not upsert_result.ok:
            messages.error(request, upsert_result.error or "Failed to update status")
            return redirect_to_team_settings(team_key, "controls")

        if request.headers.get("HX-Request"):
            return render(
                request,
                "controls/controls_table.html.j2",
                {"controls": controls_table_context(request, control.catalog)},
            )

        messages.success(request, "Control status updated.")
        return redirect_to_team_settings(team_key, "controls")


class ProductControlsStatusView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Handle product-level control status update POST (HTMX inline)."""

    allowed_roles = list(ADMINISTER)

    def post(self, request: HttpRequest, team_key: str, product_id: str) -> HttpResponse:
        from sbomify.apps.core.models import Product

        if not _check_team_key_matches_session(request, team_key):
            messages.error(request, "Unauthorized: workspace mismatch")
            return redirect("core:product_details", product_id=product_id)

        user = cast(User, request.user)
        control_id = request.POST.get("control_id", "")
        status = request.POST.get("status", "")

        if not control_id or not status:
            messages.error(request, "Missing control or status")
            return redirect("core:product_details", product_id=product_id)

        try:
            control = Control.objects.get(id=control_id, catalog__team__key=team_key)
        except Control.DoesNotExist:
            messages.error(request, "Control not found")
            return redirect("core:product_details", product_id=product_id)

        try:
            product = Product.objects.get(id=product_id, team__key=team_key)
        except Product.DoesNotExist:
            messages.error(request, "Product not found")
            return redirect("core:product_details", product_id=product_id)

        upsert_result = upsert_status(control, product, status, user)
        if not upsert_result.ok:
            messages.error(request, upsert_result.error or "Failed to update status")
            return redirect("core:product_details", product_id=product_id)

        if request.headers.get("HX-Request"):
            return render(
                request,
                "controls/controls_table.html.j2",
                {"controls": controls_table_context(request, control.catalog, product)},
            )

        messages.success(request, "Control status updated.")
        return redirect("core:product_details", product_id=product_id)


class BulkCategoryUpdateView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Bulk update all controls in a category to a single status."""

    allowed_roles = list(ADMINISTER)

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from sbomify.apps.controls.services.status_service import bulk_update_statuses
        from sbomify.apps.teams.utils import redirect_to_team_settings

        if not _check_team_key_matches_session(request, team_key):
            messages.error(request, "Unauthorized: workspace mismatch")
            return redirect_to_team_settings(team_key, "controls")

        user = cast(User, request.user)
        category = request.POST.get("category", "")
        status = request.POST.get("status", "")
        catalog_id = request.POST.get("catalog_id", "")

        if not category or not status:
            messages.error(request, "Missing category or status")
            return redirect_to_team_settings(team_key, "controls")

        # Get all controls in this category for this team, scoped to a specific catalog
        controls_qs = Control.objects.filter(catalog__team__key=team_key, group=category)
        if catalog_id:
            controls_qs = controls_qs.filter(catalog_id=catalog_id)
        controls = controls_qs.values_list("id", flat=True)

        if not controls.exists():
            messages.error(request, "No controls found in this category")
            return redirect_to_team_settings(team_key, "controls")

        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return redirect_to_team_settings(team_key, "controls")

        updates = [{"control_id": cid, "status": status} for cid in controls]

        if len(updates) > 500:
            messages.error(request, f"Category has {len(updates)} controls, exceeding the 500 limit")
            return redirect_to_team_settings(team_key, "controls")

        result = bulk_update_statuses(updates, user, team=team)

        if not result.ok:
            messages.error(request, result.error or "Bulk update failed")
        else:
            messages.success(request, f"Set {result.value} controls in {category} to {status}.")

        if request.headers.get("HX-Request"):
            control = controls_qs.select_related("catalog__team").first()
            if control is not None:
                return render(
                    request,
                    "controls/controls_table.html.j2",
                    {"controls": controls_table_context(request, control.catalog)},
                )

        return redirect_to_team_settings(team_key, "controls")
