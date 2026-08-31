from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.sboms.hardware_inventory import get_hardware_inventory, part_search_term

CARD_TEMPLATE = "sboms/components/hardware_inventory_card.html.j2"


class SbomHardwareInventoryView(View):
    """Lazy-loaded (hx-get) hardware-parts inventory card for one SBOM.

    Rendered as an HTMX partial so the per-SBOM artifact read does not block the
    detail-page render. Authorization is delegated to ``get_hardware_inventory``
    (the same ``can("component:access")`` used by the other SBOM read paths), so
    the card works on both the private and public item pages without a login
    mixin. Any failure or an empty inventory renders nothing — with
    ``hx-swap="outerHTML"`` the placeholder simply collapses, never leaking
    existence or erroring on a software-only SBOM.
    """

    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        result = get_hardware_inventory(request, sbom_id)
        if not result.ok or not (result.value or {}).get("count"):
            return HttpResponse("")
        inventory: dict[str, Any] = result.value or {}
        return render(
            request,
            CARD_TEMPLATE,
            {
                "hardware_inventory": inventory,
                "part_terms": [part_search_term(p) for p in inventory["parts"]],
                "sbom_id": sbom_id,
            },
        )
