"""Derive a crypto-asset inventory (CBOM) from a CycloneDX document.

CycloneDX 1.6+ represents cryptographic assets as ``components[]`` entries with
``type == "cryptographic-asset"`` and a ``cryptoProperties`` object (algorithm /
certificate / protocol / related-crypto-material). sbomify stores the raw
artifact immutably in S3 and never extracts these (ADR-004), so the inventory is
**derived on read** from the stored document — there is no separate persisted
copy to keep in sync.

``derive_crypto_inventory`` is a pure function over the parsed JSON: it filters
the crypto-asset components and projects the PQC-relevant fields into plain
dataclasses. It tolerates every CBOM lineage: the legacy IBM CBOM 1.0
CycloneDX-1.4 fork (``type == "crypto-asset"``; ``variant`` and
``implementationLevel`` spellings; security levels at the ``cryptoProperties``
root), CycloneDX 1.6, and 1.7 (``curve`` -> ``ellipticCurve``, added
``algorithmFamily``), plus malformed/partial entries. It does not validate the
document — callers upload through the schema validator; this only reads.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeGuard

CRYPTO_ASSET_TYPE = "cryptographic-asset"
# The pre-standard IBM CBOM lineage (a CycloneDX 1.4 fork) that older
# CBOMkit / sonar-cryptography releases emitted; upstreamed into 1.6 as
# ``cryptographic-asset``.
LEGACY_CRYPTO_ASSET_TYPE = "crypto-asset"
_CRYPTO_ASSET_TYPES = frozenset({CRYPTO_ASSET_TYPE, LEGACY_CRYPTO_ASSET_TYPE})


def is_crypto_asset(component: Any) -> TypeGuard[dict[str, Any]]:
    """True when a component is a cryptographic asset in any CBOM lineage:
    typed as one, or carrying a ``cryptoProperties`` object.

    The one predicate shared by upload auto-detect, the CBOM backfill command,
    and inventory derivation. The sides must never diverge: a document detected
    as a CBOM by one predicate but inventoried by a stricter one renders a
    CBOM page with an empty inventory.
    """
    return isinstance(component, dict) and (
        component.get("type") in _CRYPTO_ASSET_TYPES or "cryptoProperties" in component
    )


@dataclass(frozen=True)
class CryptoAsset:
    """One ``cryptographic-asset`` component, projected for inventory + PQC use."""

    name: str | None
    bom_ref: str | None
    oid: str | None
    asset_type: str | None  # algorithm | certificate | protocol | related-crypto-material

    # algorithmProperties projection (the fields PQC readiness keys on)
    primitive: str | None = None
    algorithm_family: str | None = None  # CycloneDX 1.7
    parameter_set: str | None = None
    curve: str | None = None  # 1.6 "curve" / 1.7 "ellipticCurve"
    nist_quantum_security_level: int | None = None
    classical_security_level: int | None = None
    crypto_functions: tuple[str, ...] = ()
    mode: str | None = None
    padding: str | None = None
    execution_environment: str | None = None
    implementation_platform: str | None = None
    certification_level: tuple[str, ...] = ()  # FIPS 140 / Common Criteria levels

    # 1.7 registry normalization: one canonical identifier however the source
    # spelled it ("prime256v1" == "secp256r1" == "nist/P-256"). None when the
    # registry doesn't know the name; the raw value stays in curve/family.
    normalized_family: str | None = None
    normalized_curve: str | None = None
    registry_unrecognized: bool = False  # named a curve/family the registry lacks

    # other asset-type sub-objects kept as-is (raw); less central to PQC scoring
    certificate: dict[str, Any] | None = None
    protocol: dict[str, Any] | None = None
    related_material: dict[str, Any] | None = None

    # full cryptoProperties for any downstream field this projection omits
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class CryptoEdge:
    """A resolved cross-reference between two crypto assets (certificate ->
    signature algorithm, key material -> algorithm, protocol -> suite member).
    Sources: 1.7 ``relatedCryptographicAssets`` plus the deprecated 1.6 ref
    fields (``signatureAlgorithmRef``, ``subjectPublicKeyRef``,
    ``algorithmRef``, ``securedBy.algorithmRef``, ``cryptoRefArray``)."""

    source: str
    relation: str
    target: str
    resolved: bool  # target bom-ref exists in this inventory


@dataclass(frozen=True)
class CryptoInventory:
    """The crypto assets derived from a single CycloneDX document."""

    assets: tuple[CryptoAsset, ...] = ()
    edges: tuple[CryptoEdge, ...] = ()

    @property
    def count(self) -> int:
        return len(self.assets)

    @property
    def by_asset_type(self) -> dict[str, int]:
        """Count of assets per ``assetType`` (entries with no assetType omitted)."""
        return dict(Counter(a.asset_type for a in self.assets if a.asset_type))


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _str_or_none(value: Any) -> str | None:
    """Coerce a CycloneDX scalar to ``str`` (keep hashable, schema-clean).

    A spec-conformant value is already a string. A scalar (int/float/bool) is
    stringified so data is not lost. Anything else (dict/list) is dropped to
    ``None`` — it would be unhashable for ``by_asset_type`` and would violate the
    ``str | None`` API schema, both of which the module promises never to raise on.
    """
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):  # bool is an int subclass — fine
        return str(value)
    return None


def _certification_levels(value: Any) -> tuple[str, ...]:
    """1.6+ certificationLevel is an array; the legacy lineage used a bare string."""
    if isinstance(value, str):
        return (value,)
    return _str_tuple(value)


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(v) for v in value if isinstance(v, (str, int, float)))


def _project_asset(component: dict[str, Any]) -> CryptoAsset:
    from sbomify.apps.sboms.crypto_registry import curve_for_oid, normalize_curve, normalize_family

    crypto = _dict_or_none(component.get("cryptoProperties")) or {}
    algo = _dict_or_none(crypto.get("algorithmProperties")) or {}
    curve = _str_or_none(algo.get("curve") or algo.get("ellipticCurve"))
    family = _str_or_none(algo.get("algorithmFamily"))
    name = _str_or_none(component.get("name"))
    oid = _str_or_none(crypto.get("oid") or component.get("oid"))
    normalized_curve = normalize_curve(curve) or curve_for_oid(oid)
    normalized_family = normalize_family(family) or normalize_family(name)
    # Legacy IBM CBOM 1.0 spellings: ``variant`` (renamed
    # ``parameterSetIdentifier`` in 1.6), ``implementationLevel`` (renamed
    # ``executionEnvironment``), and security levels on the cryptoProperties
    # root rather than inside algorithmProperties.
    return CryptoAsset(
        name=name,
        bom_ref=_str_or_none(component.get("bom-ref")),
        oid=oid,
        asset_type=_str_or_none(crypto.get("assetType")),
        primitive=_str_or_none(algo.get("primitive")),
        algorithm_family=family,
        parameter_set=_str_or_none(algo.get("parameterSetIdentifier") or algo.get("variant")),
        curve=curve,
        nist_quantum_security_level=_as_int(
            algo.get("nistQuantumSecurityLevel", crypto.get("nistQuantumSecurityLevel"))
        ),
        classical_security_level=_as_int(algo.get("classicalSecurityLevel", crypto.get("classicalSecurityLevel"))),
        crypto_functions=_str_tuple(algo.get("cryptoFunctions")),
        mode=_str_or_none(algo.get("mode")),
        padding=_str_or_none(algo.get("padding")),
        execution_environment=_str_or_none(algo.get("executionEnvironment") or algo.get("implementationLevel")),
        implementation_platform=_str_or_none(algo.get("implementationPlatform")),
        certification_level=_certification_levels(algo.get("certificationLevel")),
        normalized_family=normalized_family,
        normalized_curve=normalized_curve,
        registry_unrecognized=bool((curve and not normalized_curve) or (family and not normalized_family)),
        certificate=_dict_or_none(crypto.get("certificateProperties")),
        protocol=_dict_or_none(crypto.get("protocolProperties")),
        related_material=_dict_or_none(crypto.get("relatedCryptoMaterialProperties")),
        raw=crypto or None,
    )


def derive_crypto_inventory(sbom_json: dict[str, Any] | None) -> CryptoInventory:
    """Project the crypto-asset components of a CycloneDX document.

    Scans ``components`` plus ``metadata.component`` (a pure CBOM may carry its
    sole crypto asset there), using the same ``is_crypto_asset`` predicate as
    upload auto-detect. Returns an empty inventory for a non-dict input or a
    document with no crypto assets. Never raises on partial data.
    """
    if not isinstance(sbom_json, dict):
        return CryptoInventory()
    components = sbom_json.get("components")
    candidates = [c for c in components if is_crypto_asset(c)] if isinstance(components, list) else []
    metadata = sbom_json.get("metadata")
    meta_component = metadata.get("component") if isinstance(metadata, dict) else None
    if is_crypto_asset(meta_component):
        seen_refs = {c.get("bom-ref") for c in candidates if c.get("bom-ref")}
        if meta_component.get("bom-ref") not in seen_refs:
            candidates.insert(0, meta_component)
    assets = tuple(_project_asset(c) for c in candidates)
    return CryptoInventory(assets=assets, edges=_extract_edges(candidates, assets))


def _extract_edges(candidates: list[dict[str, Any]], assets: tuple[CryptoAsset, ...]) -> tuple[CryptoEdge, ...]:
    known_refs = {a.bom_ref for a in assets if a.bom_ref}
    edges: list[CryptoEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source: str | None, relation: str, target: Any) -> None:
        if not source or not isinstance(target, str) or not target:
            return
        key = (source, relation, target)
        if key in seen:
            return
        seen.add(key)
        edges.append(CryptoEdge(source=source, relation=relation, target=target, resolved=target in known_refs))

    for component in candidates:
        source = component.get("bom-ref")
        source = source if isinstance(source, str) else None
        crypto = _dict_or_none(component.get("cryptoProperties")) or {}
        certificate = _dict_or_none(crypto.get("certificateProperties")) or {}
        add(source, "signatureAlgorithm", certificate.get("signatureAlgorithmRef"))
        add(source, "subjectPublicKey", certificate.get("subjectPublicKeyRef"))
        material = _dict_or_none(crypto.get("relatedCryptoMaterialProperties")) or {}
        add(source, "algorithm", material.get("algorithmRef"))
        secured_by = _dict_or_none(material.get("securedBy")) or {}
        add(source, "securedBy", secured_by.get("algorithmRef"))
        protocol = _dict_or_none(crypto.get("protocolProperties")) or {}
        crypto_refs = protocol.get("cryptoRefArray")
        if isinstance(crypto_refs, list):
            for ref in crypto_refs:
                add(source, "cryptoRef", ref)
        for sub in (certificate, material, protocol):
            related = sub.get("relatedCryptographicAssets")
            if isinstance(related, list):
                for item in related:
                    if isinstance(item, dict):
                        add(source, _str_or_none(item.get("type")) or "related", item.get("ref"))
    return tuple(edges)


CERT_EXPIRING_SOON_DAYS = 90


def parse_cert_datetime(raw: Any) -> datetime | None:
    """Parse a CycloneDX certificate timestamp (datetime or bare date), UTC-aware.

    The one parser both the per-certificate view and the fleet rollup use, so
    the two surfaces can never disagree about the same certificate.
    """
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def cert_expiry_state(raw: Any, now: datetime) -> tuple[int | None, bool, bool]:
    """``(days_to_expiry, expired, expiring_soon)`` for a notValidAfter value."""
    parsed = parse_cert_datetime(raw)
    if parsed is None:
        return None, False, False
    days = (parsed - now).days
    return days, days < 0, 0 <= days <= CERT_EXPIRING_SOON_DAYS


def certificate_expiry_summary(inventory: CryptoInventory, now: datetime | None = None) -> dict[str, Any] | None:
    """Expiry rollup over certificate assets: counts, the soonest notValidAfter,
    and the raw expiry dates.

    Persisted into PQC AssessmentRun metadata so fleet views can aggregate
    certificate posture without re-reading artifacts. The counts freeze at run
    time; ``not_valid_after`` carries the dates so read-time consumers can
    recompute a live countdown. ``None`` when the inventory holds no
    certificates.
    """
    certs = [a for a in inventory.assets if a.asset_type == "certificate" and a.certificate]
    if not certs:
        return None
    now = now or datetime.now(timezone.utc)
    expired = expiring_soon = 0
    dates: list[str] = []
    soonest: datetime | None = None
    for asset in certs:
        raw = (asset.certificate or {}).get("notValidAfter")
        parsed = parse_cert_datetime(raw)
        if parsed is None:
            continue
        dates.append(parsed.isoformat())
        if soonest is None or parsed < soonest:
            soonest = parsed
        _days, is_expired, is_expiring = cert_expiry_state(raw, now)
        if is_expired:
            expired += 1
        elif is_expiring:
            expiring_soon += 1
    return {
        "count": len(certs),
        "expired": expired,
        "expiring_soon": expiring_soon,
        "soonest_not_valid_after": soonest.isoformat() if soonest else None,
        "not_valid_after": dates,
    }
