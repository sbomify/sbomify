from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.services.sboms import get_crypto_inventory

POSTURE_TEMPLATE = "sboms/components/crypto_posture_card.html.j2"


class ComponentCryptoPostureView(View):
    """Lazy-loaded (hx-get) component-level post-quantum posture card.

    Shows the overall PQC readiness of the component's newest crypto-bearing
    artifact, as an at-a-glance signal on the component detail page (private
    and public). The newest CBOM wins; without one, the newest SBOM not known
    to be crypto-free (``has_crypto_assets`` True, or None for rows predating
    the flag) — so neither a VEX upload nor a newer crypto-free SBOM displaces
    an older crypto-bearing artifact, and known-empty rows skip the S3 read.
    Like the per-SBOM card it is an HTMX partial: a single S3 read happens after
    page render, authorization is delegated to ``get_crypto_inventory`` (so no
    private leak on the public page), and any failure or a crypto-free artifact
    renders nothing — the placeholder simply collapses.
    """

    def get(self, request: HttpRequest, component_id: str) -> HttpResponse:
        from django.db.models import QuerySet

        base = SBOM.objects.filter(component_id=component_id).order_by("-created_at")

        def newest(queryset: QuerySet[SBOM]) -> str | None:
            first = queryset.values_list("id", flat=True).first()
            return str(first) if first is not None else None

        latest_id = newest(base.filter(bom_type=SBOM.BomType.CBOM)) or newest(
            base.filter(bom_type=SBOM.BomType.SBOM).exclude(has_crypto_assets=False)
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
