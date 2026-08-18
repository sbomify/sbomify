from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.views import View

from sbomify.apps.core.authz import can
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import Component
from sbomify.apps.core.services.component_security import models_q_hardware_bearing
from sbomify.apps.sboms.hardware_inventory import get_hardware_inventory
from sbomify.apps.sboms.models import SBOM

# The card's own search-term builder — the page embeds that same table, and a
# second copy would drift into a search matching different fields per page.
from sbomify.apps.sboms.views.sbom_hardware_inventory import _part_term

TEMPLATE = "sboms/component_hardware.html.j2"


class ComponentHardwareView(LoginRequiredMixin, View):
    """Component-level hardware (HBOM) parts page.

    Lists the parts of the component's newest hardware-bearing artifact: the
    newest HBOM wins, and without one the newest SBOM stamped
    ``has_hardware_components`` — so neither a VEX upload nor a newer
    software-only SBOM displaces a hardware artifact. The parts are derived from
    the stored document on every read and persisted nowhere (ADR-004).

    Login is required because the page renders inside the authenticated
    dashboard shell, which reads the signed-in user. ``can`` still decides
    whether *this* user may read *this* component; the public equivalent of this
    view is the inventory card on the public artifact page.

    Authorization is the ``component:access`` check the inventory endpoints
    delegate to, applied to the component itself so the answer is the same
    whether or not a hardware artifact exists — the empty-state page must not
    become a way to probe a private component. A component with no hardware
    artifact renders that empty state, as does an artifact carrying no parts or
    one storage cannot return: this is a read-only view, never a 500.
    """

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        component = Component.objects.select_related("team").filter(pk=component_id).first()
        # 404, not 403: a private component must not be confirmed to exist.
        if component is None or not can(request, "component:access", component):
            return error_response(request, HttpResponseNotFound("Component not found"))

        artifacts = (
            SBOM.objects.filter(component_id=component_id)
            .filter(models_q_hardware_bearing())
            .order_by("-created_at")
            .values("id", "version", "bom_type")
        )
        artifact = artifacts.filter(bom_type=SBOM.BomType.HBOM).first() or artifacts.first()

        inventory: dict[str, Any] | None = None
        if artifact is not None:
            result = get_hardware_inventory(request, artifact["id"])
            if result.ok and (result.value or {}).get("count"):
                inventory = result.value

        return render(
            request,
            TEMPLATE,
            {
                "component": component,
                "artifact": artifact,
                "hardware_inventory": inventory,
                "part_terms": [_part_term(part) for part in inventory["parts"]] if inventory else [],
            },
        )
