"""CycloneDX 1.7 cryptography-registry lookups over a vendored data file.

The registry (https://cyclonedx.org/registry/cryptography/) names ~96 algorithm
families and ~246 namespaced elliptic curves, each curve carrying its OID and
cross-namespace aliases (``nist/P-256`` == ``secg/secp256r1`` ==
``x962/prime256v1``). It versions independently of the spec, so the data file
is vendored under ``data/`` and refreshed with the
``refresh_crypto_registry`` management command.

Normalization folds the free-text names the 1.6-era toolchain emits onto one
canonical registry identifier per curve group (namespace preference:
nist > secg > x962 > brainpool > rest), so two documents naming the same curve
differently inventory identically. Unknown names return ``None`` — callers
keep the raw value and flag it unrecognized rather than dropping data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).parent / "data" / "cyclonedx_cryptography_registry.json"
_NAMESPACE_RANK = {"nist": 0, "secg": 1, "x962": 2, "brainpool": 3}


@dataclass(frozen=True)
class _RegistryTables:
    curve_by_name: dict[str, str]
    curve_by_oid: dict[str, str]
    aliases_by_canonical: dict[str, tuple[str, ...]]
    family_by_name: dict[str, str]
    last_updated: str | None


def _rank(canonical: str) -> tuple[int, str]:
    namespace = canonical.split("/", 1)[0]
    return (_NAMESPACE_RANK.get(namespace, 99), canonical)


def build_tables(data: dict[str, Any]) -> _RegistryTables:
    """Build lookup tables from registry data, skipping malformed entries.

    Tolerant by contract: inventory derivation promises never to raise, so a
    shape-drifted entry is dropped rather than crashing every crypto surface.
    The refresh command calls this on candidate data before writing, so a file
    that would produce empty tables never lands.
    """
    curve_by_name: dict[str, str] = {}
    curve_by_oid: dict[str, str] = {}
    aliases_by_canonical: dict[str, tuple[str, ...]] = {}
    for family in data.get("ellipticCurves") or []:
        if not isinstance(family, dict):
            continue
        namespace = family.get("name") or "other"
        for curve in family.get("curves") or []:
            if not isinstance(curve, dict) or not isinstance(curve.get("name"), str):
                continue
            aliases = [
                a for a in (curve.get("aliases") or []) if isinstance(a, dict) and a.get("category") and a.get("name")
            ]
            candidates = [f"{namespace}/{curve['name']}"] + [f"{a['category']}/{a['name']}" for a in aliases]
            canonical = min(candidates, key=_rank)
            bare_names = [curve["name"]] + [a["name"] for a in aliases]
            for name in bare_names + candidates:
                curve_by_name.setdefault(name.lower(), canonical)
            if isinstance(curve.get("oid"), str):
                curve_by_oid.setdefault(curve["oid"], canonical)
            aliases_by_canonical.setdefault(canonical, tuple(sorted(set(bare_names))))
    family_by_name = {
        str(algo["family"]).lower(): str(algo["family"])
        for algo in data.get("algorithms") or []
        if isinstance(algo, dict) and isinstance(algo.get("family"), str)
    }
    return _RegistryTables(
        curve_by_name=curve_by_name,
        curve_by_oid=curve_by_oid,
        aliases_by_canonical=aliases_by_canonical,
        family_by_name=family_by_name,
        last_updated=data.get("lastUpdated") if isinstance(data.get("lastUpdated"), str) else None,
    )


@cache
def _tables() -> _RegistryTables:
    try:
        data: dict[str, Any] = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A missing/corrupt vendored file degrades to no normalization rather
        # than crashing every inventory, posture, and dashboard render.
        return _RegistryTables({}, {}, {}, {}, None)
    return build_tables(data if isinstance(data, dict) else {})


def normalize_curve(value: str | None) -> str | None:
    """Canonical registry identifier for a curve named in any spelling, else None."""
    if not value or not isinstance(value, str):
        return None
    return _tables().curve_by_name.get(value.strip().lower())


def curve_for_oid(oid: str | None) -> str | None:
    if not oid or not isinstance(oid, str):
        return None
    return _tables().curve_by_oid.get(oid.strip())


def curve_aliases(canonical: str) -> tuple[str, ...]:
    """Every bare (un-namespaced) name the registry lists for a canonical curve."""
    return _tables().aliases_by_canonical.get(canonical, ())


def normalize_family(value: str | None) -> str | None:
    """Registry algorithmFamily for a case-insensitive exact name match, else None."""
    if not value or not isinstance(value, str):
        return None
    return _tables().family_by_name.get(value.strip().lower())


def registry_last_updated() -> str | None:
    return _tables().last_updated
