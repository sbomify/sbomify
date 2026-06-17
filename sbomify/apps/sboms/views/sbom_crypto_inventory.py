from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.sboms.services.sboms import get_crypto_inventory

CARD_TEMPLATE = "sboms/components/crypto_inventory_card.html.j2"


class SbomCryptoInventoryView(View):
    """Lazy-loaded (hx-get) crypto-asset inventory card for one SBOM.

    Rendered as an HTMX partial so the per-SBOM artifact read does not block the
    detail-page render. Authorization is delegated to ``get_crypto_inventory``
    (the same ``check_component_access`` used by the other SBOM read paths), so
    the card works on both the private and public item pages without a login
    mixin. Any failure or an empty inventory renders nothing — with
    ``hx-swap="outerHTML"`` the placeholder simply collapses, never leaking
    existence or erroring on an ordinary (non-crypto) SBOM.
    """

    def get(self, request: HttpRequest, sbom_id: str) -> HttpResponse:
        result = get_crypto_inventory(request, sbom_id)
        if not result.ok or not (result.value or {}).get("count"):
            return HttpResponse("")
        return render(request, CARD_TEMPLATE, {"crypto_inventory": result.value})
