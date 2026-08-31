"""Workspace hardware rollup: which parts appear where, across the portfolio.

The crypto rollup answers "which components use weak algorithms"; this
answers the supply-chain concentration question — "which parts appear across
my products". Parts are grouped by manufacturer and part name, and a part
carried by more than one product is flagged: that is the single-source
concentration signal an NDAA §877 or EO 14415 review starts from.

Derived on read from the stored artifacts (ADR-004, nothing persisted) and
cached like the crypto rollup. The database query count is flat in the
number of components — one queryset per selection step and one for the
product mapping; the per-artifact document reads are S3 fetches, each cached
by the per-SBOM inventory cache underneath the rollup cache.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, cast

from botocore.exceptions import BotoCoreError, ClientError
from django.core.cache import cache as django_cache

from sbomify.apps.core.models import Component
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.sboms.hardware_inventory import HardwareInventory, derive_hardware_inventory
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.services.crypto_dashboard import _newest_by_component
from sbomify.logging import getLogger

log = getLogger(__name__)

_CACHE_TTL_SECONDS = 300


def _newest_hardware_stamped(component_ids: list[str]) -> dict[str, str]:
    """Newest ``bom_type=sbom`` artifact per component that upload stamped
    hardware-bearing — the fallback when a component has no HBOM."""
    rows = (
        SBOM.objects.filter(component_id__in=component_ids, bom_type=SBOM.BomType.SBOM, has_hardware_components=True)
        .order_by("component_id", "-created_at")
        .distinct("component_id")
        .values_list("component_id", "id")
    )
    return {component_id: sbom_id for component_id, sbom_id in rows}


def _load_inventory(sbom_id: str, filename: str | None) -> HardwareInventory:
    """The artifact's parts, from the same per-SBOM cache the inventory card
    fills; a failed or unparseable read degrades to an empty inventory."""
    if not filename:
        return HardwareInventory()
    cache_key = f"hardware-rollup-inventory:v1:{sbom_id}"
    cached = django_cache.get(cache_key)
    if cached is not None:
        return cast("HardwareInventory", cached)
    try:
        raw = S3Client("SBOMS").get_sbom_data(filename)
    except (BotoCoreError, ClientError):
        log.warning("Hardware rollup: object store error for SBOM %s", sbom_id, exc_info=True)
        return HardwareInventory()
    try:
        document = json.loads(raw) if raw else None
    except (ValueError, TypeError, UnicodeDecodeError):
        document = None
    # include_root=False: the rollup counts constituent parts, and the root
    # assembly is the component's own board — counting it would make every
    # board its own "part" and identically-named boards read as shared.
    inventory = derive_hardware_inventory(document if isinstance(document, dict) else None, include_root=False)
    django_cache.set(cache_key, inventory, _CACHE_TTL_SECONDS)
    return inventory


def build_workspace_hardware_rollup(team_id: int) -> dict[str, Any]:
    cache_key = f"workspace-hardware-rollup:{team_id}"
    cached = django_cache.get(cache_key)
    if cached is not None:
        return cast("dict[str, Any]", cached)

    components = list(
        Component.objects.filter(team_id=team_id, component_type=Component.ComponentType.BOM)
        .order_by("name")
        .values("id", "name")
    )
    component_ids = [component["id"] for component in components]
    component_names = {component["id"]: component["name"] for component in components}

    # Newest HBOM wins; without one, the newest SBOM stamped hardware-bearing —
    # the same selection rule the component hardware page applies, so the
    # rollup and the page it links to can never disagree about the artifact.
    newest_hbom = _newest_by_component(component_ids, SBOM.BomType.HBOM)
    newest_stamped = _newest_hardware_stamped(component_ids)
    chosen: dict[str, str] = {}
    for component_id in component_ids:
        sbom_id = newest_hbom.get(component_id) or newest_stamped.get(component_id)
        if sbom_id:
            chosen[component_id] = sbom_id

    filenames = dict(SBOM.objects.filter(id__in=list(chosen.values())).values_list("id", "sbom_filename"))

    # One query maps every hardware-bearing component to its products.
    product_rows = Component.products.through.objects.filter(component_id__in=list(chosen)).values_list(
        "component_id", "product__name"
    )
    products_by_component: dict[str, set[str]] = {}
    for component_id, product_name in product_rows:
        products_by_component.setdefault(component_id, set()).add(product_name)

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    parts_total = 0
    type_counts: Counter[str] = Counter()
    for component_id, sbom_id in chosen.items():
        inventory = _load_inventory(sbom_id, filenames.get(sbom_id))
        for part in inventory.parts:
            if not part.name:
                continue
            parts_total += 1
            if part.type:
                type_counts[part.type] += 1
            key = (part.manufacturer or "", part.name)
            group = groups.setdefault(
                key,
                {
                    "manufacturer": part.manufacturer or "",
                    "name": part.name,
                    "types": set(),
                    "components": set(),
                    "products": set(),
                },
            )
            if part.type:
                group["types"].add(part.type)
            group["components"].add(component_names.get(component_id, component_id))
            group["products"].update(products_by_component.get(component_id, set()))

    rows = [
        {
            "manufacturer": group["manufacturer"],
            "name": group["name"],
            # One agreed type reads as itself; artifacts disagreeing about the
            # same part read as "mixed" rather than whichever came first.
            "type": next(iter(group["types"])) if len(group["types"]) == 1 else ("mixed" if group["types"] else ""),
            "components": sorted(group["components"]),
            "products": sorted(group["products"]),
            "shared": len(group["products"]) > 1,
        }
        for group in groups.values()
    ]
    # Concentration first: the parts more than one product depends on are the
    # reason this page exists; ties break alphabetically for a stable read.
    rows.sort(key=lambda row: (-len(row["products"]), row["manufacturer"].lower(), row["name"].lower()))

    manufacturer_counts = Counter(row["manufacturer"] for row in rows if row["manufacturer"])
    rollup = {
        "rows": rows,
        "parts_total": parts_total,
        "distinct_parts": len(rows),
        "shared_parts": sum(1 for row in rows if row["shared"]),
        "components_with_hardware": len(chosen),
        "by_type": dict(type_counts),
        "top_manufacturers": [{"name": name, "parts": count} for name, count in manufacturer_counts.most_common(10)],
    }
    django_cache.set(cache_key, rollup, _CACHE_TTL_SECONDS)
    return rollup
