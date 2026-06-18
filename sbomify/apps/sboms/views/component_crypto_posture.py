from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.services.sboms import get_crypto_inventory

POSTURE_TEMPLATE = "sboms/components/crypto_posture_card.html.j2"


class ComponentCryptoPostureView(View):
    """Lazy-loaded (hx-get) component-level post-quantum posture card.

    Shows the overall PQC readiness of the component's most recent artifact, as
    an at-a-glance signal on the component detail page (private and public).
    Like the per-SBOM card it is an HTMX partial: a single S3 read happens after
    page render, authorization is delegated to ``get_crypto_inventory`` (so no
    private leak on the public page), and any failure or a crypto-free artifact
    renders nothing — the placeholder simply collapses.
    """

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        latest_id = (
            SBOM.objects.filter(component_id=component_id).order_by("-created_at").values_list("id", flat=True).first()
        )
        if latest_id is None:
            return HttpResponse("")

        result = get_crypto_inventory(request, latest_id)
        if not result.ok or not (result.value or {}).get("count"):
            return HttpResponse("")

        return render(
            request,
            POSTURE_TEMPLATE,
            {"posture": result.value, "component_id": component_id, "sbom_id": latest_id},
        )
