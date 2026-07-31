"""Workspace-level crypto readiness rollup.

Aggregates the persisted PQC AssessmentRun results (never the raw artifacts:
no S3 fan-out) across every component in a workspace: one row per component
keyed on its newest crypto-bearing artifact (newest CBOM, else newest SBOM),
with the latest completed pqc-readiness run's verdict, per-status counts,
vulnerable algorithm names, and the certificate expiry summary the plugin
stamps into run metadata.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, cast

from django.core.cache import cache as django_cache
from django.utils import timezone

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.crypto_inventory import cert_expiry_state
from sbomify.apps.sboms.models import SBOM

# The rollup reads persisted runs only, so short caching just deduplicates
# repeated page loads; certificate countdowns recompute from stored dates on
# every build, so staleness is bounded by the TTL, not by scan recency.
_CACHE_TTL_SECONDS = 120

PQC_PLUGIN = "pqc-readiness"

# Component verdicts, worst first. "no_crypto" = assessed, nothing to grade
# (skipped run); "not_assessed" = no artifact or no run yet.
_VERDICT_ORDER = {"at_risk": 0, "needs_review": 1, "ready": 2, "no_crypto": 3, "not_assessed": 4}


def _title_asset_name(title: str) -> str:
    """Asset name from a finding title, tolerating both separator eras
    (colon in new runs, em-dash in runs stored before the rename)."""
    for separator in (": ", " — "):
        if separator in title:
            return title.split(separator)[0]
    return title


def _newest_by_component(
    component_ids: list[str], bom_type: str, *, exclude_crypto_free: bool = False
) -> dict[str, str]:
    queryset = SBOM.objects.filter(component_id__in=component_ids, bom_type=bom_type)
    if exclude_crypto_free:
        queryset = queryset.exclude(has_crypto_assets=False)
    rows = queryset.order_by("component_id", "-created_at").distinct("component_id").values_list("component_id", "id")
    return {component_id: sbom_id for component_id, sbom_id in rows}


def _live_cert_counts(certificates: dict[str, Any]) -> dict[str, Any]:
    """Recompute expired/expiring from the stored expiry dates at read time.

    The counts stamped into run metadata freeze at scan time; a countdown is
    time-sensitive, so when the run recorded the raw dates recount them
    against now. Runs predating the dates list keep their frozen counts.
    """
    dates = certificates.get("not_valid_after")
    if not isinstance(dates, list) or not dates:
        return certificates
    now = timezone.now()
    expired = expiring_soon = 0
    for raw in dates:
        _days, is_expired, is_expiring = cert_expiry_state(raw, now)
        if is_expired:
            expired += 1
        elif is_expiring:
            expiring_soon += 1
    return {**certificates, "expired": expired, "expiring_soon": expiring_soon}


def build_workspace_crypto_rollup(team_id: int) -> dict[str, Any]:
    cache_key = f"workspace-crypto-rollup:{team_id}"
    cached = django_cache.get(cache_key)
    if cached is not None:
        return cast("dict[str, Any]", cached)

    components = list(
        Component.objects.filter(team_id=team_id, component_type=Component.ComponentType.BOM)
        .order_by("name")
        .values("id", "name")
    )
    component_ids = [c["id"] for c in components]
    newest_cbom = _newest_by_component(component_ids, SBOM.BomType.CBOM)
    # Prefer the newest crypto-bearing SBOM so a later crypto-free upload
    # never evicts a component's assessed crypto posture (the component-page
    # posture card applies the same rule); fall back to any newest SBOM so
    # the crypto-free stamp can still say "no crypto".
    newest_crypto_sbom = _newest_by_component(component_ids, SBOM.BomType.SBOM, exclude_crypto_free=True)
    newest_sbom = _newest_by_component(component_ids, SBOM.BomType.SBOM)
    chosen = {
        c["id"]: newest_cbom.get(c["id"]) or newest_crypto_sbom.get(c["id"]) or newest_sbom.get(c["id"])
        for c in components
    }
    # The dispatch gate skips crypto-gated plugins for artifacts stamped
    # crypto-free, so no skipped run exists for them; the stamp itself is the
    # "no crypto" verdict.
    crypto_free_sboms = set(
        SBOM.objects.filter(id__in=[s for s in chosen.values() if s], has_crypto_assets=False).values_list(
            "id", flat=True
        )
    )

    # Two-step read keeps result blobs off the wire for skipped runs (the
    # common case once the plugin runs on every SBOM): fetch lightweight
    # metadata first, then the full result only for runs that assessed
    # something.
    run_meta = list(
        AssessmentRun.objects.filter(
            sbom_id__in=[sbom_id for sbom_id in chosen.values() if sbom_id],
            plugin_name=PQC_PLUGIN,
            status="completed",
        )
        .order_by("sbom_id", "-created_at")
        .distinct("sbom_id")
        .values("id", "sbom_id", "result_skipped", "created_at")
    )
    blob_ids = [m["id"] for m in run_meta if m["result_skipped"] is not True]
    blobs = (
        {str(r["id"]): r["result"] for r in AssessmentRun.objects.filter(id__in=blob_ids).values("id", "result")}
        if blob_ids
        else {}
    )
    run_by_sbom = {
        str(m["sbom_id"]): {
            "result": blobs.get(str(m["id"]), {"metadata": {"skipped": True}}),
            "created_at": m["created_at"],
        }
        for m in run_meta
    }

    rows: list[dict[str, Any]] = []
    verdict_counts: Counter[str] = Counter()
    vulnerable_components: dict[str, set[str]] = {}
    certs_total = {"expired": 0, "expiring_soon": 0}
    for component in components:
        sbom_id = chosen[component["id"]]
        run = run_by_sbom.get(str(sbom_id)) if sbom_id else None
        if run is None and sbom_id in crypto_free_sboms:
            run = {"result": {"metadata": {"skipped": True}}, "created_at": None}
        row: dict[str, Any] = {
            "id": component["id"],
            "name": component["name"],
            "sbom_id": sbom_id,
            "verdict": "not_assessed",
            "counts": {"quantum_vulnerable": 0, "review": 0, "unknown": 0, "quantum_safe": 0},
            "certificates": None,
            "assessed_at": None,
        }
        if run:
            result = run["result"] if isinstance(run["result"], dict) else {}
            raw_metadata = result.get("metadata")
            metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
            row["assessed_at"] = run["created_at"]
            if metadata.get("skipped"):
                row["verdict"] = "no_crypto"
            else:
                row["verdict"] = metadata.get("pqc_overall") or "not_assessed"
                for finding in result.get("findings") or []:
                    if not isinstance(finding, dict):
                        continue
                    raw_finding_meta = finding.get("metadata")
                    finding_meta: dict[str, Any] = raw_finding_meta if isinstance(raw_finding_meta, dict) else {}
                    status = finding_meta.get("pqc_status")
                    if status in row["counts"]:
                        row["counts"][status] += 1
                    if status == "quantum_vulnerable":
                        name = finding_meta.get("asset_name") or _title_asset_name(str(finding.get("title", "")))
                        if name:
                            vulnerable_components.setdefault(name, set()).add(component["id"])
                certificates = metadata.get("certificates")
                if isinstance(certificates, dict):
                    certificates = _live_cert_counts(certificates)
                    row["certificates"] = certificates
                    certs_total["expired"] += int(certificates.get("expired") or 0)
                    certs_total["expiring_soon"] += int(certificates.get("expiring_soon") or 0)
        verdict_counts[row["verdict"]] += 1
        rows.append(row)

    rows.sort(key=lambda r: (_VERDICT_ORDER.get(r["verdict"], 4), r["name"].lower()))
    ranked: list[tuple[str, int]] = sorted(
        ((name, len(ids)) for name, ids in vulnerable_components.items()),
        key=lambda entry: (-entry[1], entry[0]),
    )[:10]
    top_vulnerable = [{"name": name, "components": count} for name, count in ranked]
    rollup = {
        "rows": rows,
        "verdict_counts": dict(verdict_counts),
        "top_vulnerable": top_vulnerable,
        "certificates": certs_total,
        "has_crypto_data": any(r["verdict"] in ("at_risk", "needs_review", "ready") for r in rows),
    }
    django_cache.set(cache_key, rollup, _CACHE_TTL_SECONDS)
    return rollup
