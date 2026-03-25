from __future__ import annotations

from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views import View

from sbomify.apps.controls.models import Control
from sbomify.apps.controls.services.catalog_service import activate_builtin_catalog, delete_catalog, get_active_catalogs
from sbomify.apps.controls.services.status_service import get_controls_detail, upsert_status
from sbomify.apps.core.models import User
from sbomify.apps.teams.models import Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin

BULK_STATUSES = [
    ("compliant", "Compliant"),
    ("partial", "Partial"),
    ("not_implemented", "Not Implemented"),
    ("not_applicable", "N/A"),
]


def _check_team_key_matches_session(request: HttpRequest, team_key: str) -> bool:
    """Return True if the session's current_team key matches the URL team_key."""
    current_team_key: str = request.session.get("current_team", {}).get("key", "")
    return current_team_key == team_key


class ControlsCatalogView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Handle activate/deactivate catalog POST actions."""

    allowed_roles = ["owner", "admin"]

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

            deactivate_result = delete_catalog(catalog_id, team)
            if deactivate_result.ok:
                messages.success(request, "Catalog deactivated and all controls removed.")
            else:
                messages.error(request, deactivate_result.error or "Failed to deactivate catalog")
        else:
            messages.error(request, "Invalid action")

        return redirect_to_team_settings(team_key, "controls")


class ControlsStatusView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Handle individual control status update POST (HTMX inline)."""

    allowed_roles = ["owner", "admin"]

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from django.shortcuts import render

        from sbomify.apps.teams.apis import get_team
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

        # For HTMX requests, return the updated controls table partial
        if request.headers.get("HX-Request"):
            try:
                team = Team.objects.get(key=team_key)
            except Team.DoesNotExist:
                messages.error(request, "Workspace not found")
                return redirect_to_team_settings(team_key, "controls")

            catalogs_result = get_active_catalogs(team)
            catalog = catalogs_result.value[0] if catalogs_result.ok and catalogs_result.value else None

            controls_categories: list[dict[str, Any]] = []
            if catalog:
                detail_result = get_controls_detail(catalog)
                if detail_result.ok and detail_result.value is not None:
                    controls_categories = detail_result.value

            # Get team data for template context
            resp_code, team_data = get_team(request, team_key)
            if resp_code != 200:
                return redirect_to_team_settings(team_key, "controls")

            try:
                team_dict = team_data.dict() if hasattr(team_data, "dict") else team_data.model_dump()
            except AttributeError:
                team_dict = team_data

            return render(
                request,
                "controls/controls_table.html.j2",
                {
                    "team": team_dict,
                    "controls_catalog": catalog,
                    "controls_categories": controls_categories,
                    "bulk_statuses": BULK_STATUSES,
                    "is_admin_or_owner": request.session.get("current_team", {}).get("role") in ("owner", "admin"),
                },
            )

        messages.success(request, "Control status updated.")
        return redirect_to_team_settings(team_key, "controls")


class ProductControlsStatusView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Handle product-level control status update POST (HTMX inline)."""

    allowed_roles = ["owner", "admin"]

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

        # For HTMX requests, return the updated product controls partial
        if request.headers.get("HX-Request"):
            from sbomify.apps.controls.services.status_service import get_controls_detail, get_controls_summary

            catalog = control.catalog
            summary_result = get_controls_summary(catalog.team, product=product)
            detail_result = get_controls_detail(catalog, product=product)

            product_controls: dict[str, Any] | None = None
            if summary_result.ok and detail_result.ok:
                product_controls = {
                    "catalog": catalog,
                    "summary": summary_result.value,
                    "categories": detail_result.value or [],
                    "team_key": team_key,
                    "product_id": product_id,
                }

            from django.shortcuts import render

            return render(
                request,
                "controls/components/product_controls_section.html.j2",
                {
                    "product_controls": product_controls,
                    "is_admin_or_owner": request.session.get("current_team", {}).get("role") in ("owner", "admin"),
                },
            )

        messages.success(request, "Control status updated.")
        return redirect("core:product_details", product_id=product_id)


class BulkCategoryUpdateView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Bulk update all controls in a category to a single status."""

    allowed_roles = ["owner", "admin"]

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from sbomify.apps.controls.services.status_service import bulk_update_statuses
        from sbomify.apps.teams.apis import get_team
        from sbomify.apps.teams.utils import redirect_to_team_settings

        if not _check_team_key_matches_session(request, team_key):
            messages.error(request, "Unauthorized: workspace mismatch")
            return redirect_to_team_settings(team_key, "controls")

        user = cast(User, request.user)
        category = request.POST.get("category", "")
        status = request.POST.get("status", "")

        if not category or not status:
            messages.error(request, "Missing category or status")
            return redirect_to_team_settings(team_key, "controls")

        # Get all controls in this category for this team
        controls = Control.objects.filter(catalog__team__key=team_key, group=category).values_list("id", flat=True)

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

        # For HTMX, return the updated table
        if request.headers.get("HX-Request"):
            catalogs_result = get_active_catalogs(team)
            catalog = catalogs_result.value[0] if catalogs_result.ok and catalogs_result.value else None
            controls_categories: list[dict[str, Any]] = []
            if catalog:
                detail_result = get_controls_detail(catalog)
                if detail_result.ok and detail_result.value is not None:
                    controls_categories = detail_result.value

            resp_code, team_data = get_team(request, team_key)
            if resp_code != 200:
                return redirect_to_team_settings(team_key, "controls")
            try:
                team_dict = team_data.dict() if hasattr(team_data, "dict") else team_data.model_dump()
            except AttributeError:
                team_dict = team_data

            from django.shortcuts import render as django_render

            return django_render(
                request,
                "controls/controls_table.html.j2",
                {
                    "team": team_dict,
                    "controls_catalog": catalog,
                    "controls_categories": controls_categories,
                    "bulk_statuses": BULK_STATUSES,
                    "is_admin_or_owner": request.session.get("current_team", {}).get("role") in ("owner", "admin"),
                },
            )

        return redirect_to_team_settings(team_key, "controls")
