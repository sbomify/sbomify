from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.sboms.services.sboms import get_crypto_inventory

CARD_TEMPLATE = "sboms/components/crypto_inventory_card.html.j2"


def _asset_term(asset: dict[str, Any]) -> str:
    fields = (
        asset.get("name"),
        asset.get("asset_type"),
        asset.get("primitive"),
        asset.get("algorithm_family"),
        asset.get("normalized_family"),
        asset.get("curve"),
        asset.get("normalized_curve"),
        asset.get("parameter_set"),
        asset.get("oid"),
        asset.get("pqc_status"),
    )
    return " ".join(str(f) for f in fields if f).lower()


def _attach_relations(inventory: dict[str, Any]) -> None:
    """Annotate each asset with human-readable relation lines from the edge list."""
    name_by_ref = {a["bom_ref"]: (a.get("name") or a["bom_ref"]) for a in inventory["assets"] if a.get("bom_ref")}
    lines: dict[str, list[str]] = {}
    for edge in inventory.get("edges", []):
        target_name = name_by_ref.get(edge["target"], edge["target"])
        suffix = "" if edge["resolved"] else " (unresolved)"
        lines.setdefault(edge["source"], []).append(f"{edge['relation']}: {target_name}{suffix}")
        if edge["resolved"]:
            source_name = name_by_ref.get(edge["source"], edge["source"])
            lines.setdefault(edge["target"], []).append(f"{edge['relation']} of: {source_name}")
    for asset in inventory["assets"]:
        asset["relations"] = lines.get(asset.get("bom_ref") or "", [])


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
        inventory: dict[str, Any] = result.value or {}
        severity_order = {"quantum_vulnerable": 0, "review": 1, "unknown": 2, "quantum_safe": 3}
        inventory["assets"] = sorted(
            inventory["assets"],
            key=lambda a: (severity_order.get(a.get("pqc_status") or "unknown", 2), (a.get("name") or "").lower()),
        )
        _attach_relations(inventory)
        certificates = sorted(
            (a for a in inventory["assets"] if a.get("asset_type") == "certificate"),
            key=lambda a: (
                (a.get("certificate_view") or {}).get("days_to_expiry") is None,
                (a.get("certificate_view") or {}).get("days_to_expiry") or 0,
            ),
        )
        return render(
            request,
            CARD_TEMPLATE,
            {
                "crypto_inventory": inventory,
                "asset_terms": [_asset_term(a) for a in inventory["assets"]],
                "asset_statuses": [a.get("pqc_status") or "unknown" for a in inventory["assets"]],
                "certificates": certificates,
                "protocols": [a for a in inventory["assets"] if a.get("asset_type") == "protocol"],
                "sbom_id": sbom_id,
            },
        )
