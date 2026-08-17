"""The workspace's supplier list.

Vendors this workspace collects artifacts from. Reads and writes go through
``services.suppliers``; nothing here touches the ORM.
"""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.core.models import User
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.services.suppliers import (
    create_supplier,
    delete_supplier,
    list_suppliers,
    update_supplier,
)


class SupplierListView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """List, add, edit and remove the workspace's suppliers.

    Owners and admins only. The list names who the workspace is chasing for
    artifacts, which is not something a Trust Center guest should see.

    The role is checked against the workspace **in the URL**, not the one in the
    session. ``TeamRoleRequiredMixin`` reads ``session["current_team"]``, so on
    its own it answers a question about a different workspace than the one being
    acted on: an owner of A visiting B's URL clears the mixin on A's role. The
    mixin stays as a cheap first gate and ``_team`` is the authority.
    """

    allowed_roles = list(ADMINISTER)
    template_name = "teams/suppliers.html.j2"
    rows_template_name = "teams/components/supplier_rows.html.j2"

    def _team(self, request: HttpRequest, team_key: str) -> Team | None:
        user = cast(User, request.user)
        membership = (
            Member.objects.filter(user=user, team__key=team_key, role__in=self.allowed_roles)
            .select_related("team")
            .only("team", "role")
            .first()
        )
        return membership.team if membership else None

    def _rows(self, request: HttpRequest, team: Team, search: str = "") -> HttpResponse:
        result = list_suppliers(team, search)
        return render(
            request,
            self.rows_template_name,
            {"team": team, "suppliers": result.value or [], "search": search},
        )

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        team = self._team(request, team_key)
        if team is None:
            return HttpResponseForbidden("You don't have access to this workspace's suppliers")

        search = request.GET.get("search", "")
        # The search box swaps only the rows, so a keystroke does not rebuild
        # the page around it and lose focus.
        if request.headers.get("HX-Request") and request.GET.get("partial"):
            return self._rows(request, team, search)

        result = list_suppliers(team, search)
        return render(
            request,
            self.template_name,
            {"team": team, "suppliers": result.value or [], "search": search},
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        team = self._team(request, team_key)
        if team is None:
            return HttpResponseForbidden("You don't have access to this workspace's suppliers")

        data: dict[str, Any] = {
            "name": request.POST.get("name", ""),
            "contact_name": request.POST.get("contact_name", ""),
            "contact_email": request.POST.get("contact_email", ""),
            "website": request.POST.get("website", ""),
            "notes": request.POST.get("notes", ""),
        }

        supplier_id = request.POST.get("supplier_id")
        action = request.POST.get("action", "")

        # Annotated because the three branches return different type parameters
        # and only ``ok``/``error`` are read here.
        result: ServiceResult[Any]
        if action == "delete" and supplier_id:
            result = delete_supplier(team, supplier_id)
            message = "Supplier removed"
        elif supplier_id:
            result = update_supplier(team, supplier_id, data)
            message = "Supplier updated"
        else:
            result = create_supplier(team, data)
            message = "Supplier added"

        if not result.ok:
            return htmx_error_response(result.error or "Could not save the supplier")
        return htmx_success_response(message, triggers={"refresh-suppliers": True})
