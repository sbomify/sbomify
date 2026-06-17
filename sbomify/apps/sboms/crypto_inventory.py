"""Derive a crypto-asset inventory (CBOM) from a CycloneDX document.

CycloneDX 1.6+ represents cryptographic assets as ``components[]`` entries with
``type == "cryptographic-asset"`` and a ``cryptoProperties`` object (algorithm /
certificate / protocol / related-crypto-material). sbomify stores the raw
artifact immutably in S3 and never extracts these (ADR-004), so the inventory is
**derived on read** from the stored document — there is no separate persisted
copy to keep in sync.

``derive_crypto_inventory`` is a pure function over the parsed JSON: it filters
the crypto-asset components and projects the PQC-relevant fields into plain
dataclasses. It tolerates both CycloneDX 1.6 and 1.7 field spellings (1.7
renamed ``curve`` -> ``ellipticCurve`` and added ``algorithmFamily``) and
malformed/partial entries. It does not validate the document — callers upload
through the schema validator; this only reads.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

CRYPTO_ASSET_TYPE = "cryptographic-asset"


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

    # other asset-type sub-objects kept as-is (raw); less central to PQC scoring
    certificate: dict[str, Any] | None = None
    protocol: dict[str, Any] | None = None
    related_material: dict[str, Any] | None = None

    # full cryptoProperties for any downstream field this projection omits
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class CryptoInventory:
    """The crypto assets derived from a single CycloneDX document."""

    assets: tuple[CryptoAsset, ...] = ()

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


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(v) for v in value if isinstance(v, (str, int, float)))


def _project_asset(component: dict[str, Any]) -> CryptoAsset:
    crypto = _dict_or_none(component.get("cryptoProperties")) or {}
    algo = _dict_or_none(crypto.get("algorithmProperties")) or {}
    return CryptoAsset(
        name=_str_or_none(component.get("name")),
        bom_ref=_str_or_none(component.get("bom-ref")),
        oid=_str_or_none(crypto.get("oid") or component.get("oid")),
        asset_type=_str_or_none(crypto.get("assetType")),
        primitive=_str_or_none(algo.get("primitive")),
        algorithm_family=_str_or_none(algo.get("algorithmFamily")),
        parameter_set=_str_or_none(algo.get("parameterSetIdentifier")),
        curve=_str_or_none(algo.get("curve") or algo.get("ellipticCurve")),
        nist_quantum_security_level=_as_int(algo.get("nistQuantumSecurityLevel")),
        classical_security_level=_as_int(algo.get("classicalSecurityLevel")),
        crypto_functions=_str_tuple(algo.get("cryptoFunctions")),
        mode=_str_or_none(algo.get("mode")),
        padding=_str_or_none(algo.get("padding")),
        execution_environment=_str_or_none(algo.get("executionEnvironment")),
        certificate=_dict_or_none(crypto.get("certificateProperties")),
        protocol=_dict_or_none(crypto.get("protocolProperties")),
        related_material=_dict_or_none(crypto.get("relatedCryptoMaterialProperties")),
        raw=crypto or None,
    )


def derive_crypto_inventory(sbom_json: dict[str, Any] | None) -> CryptoInventory:
    """Project the ``cryptographic-asset`` components of a CycloneDX doc.

    Returns an empty inventory for a non-dict input, a document with no
    ``components``, or one with no crypto assets. Never raises on partial data.
    """
    if not isinstance(sbom_json, dict):
        return CryptoInventory()
    components = sbom_json.get("components")
    if not isinstance(components, list):
        return CryptoInventory()
    assets = tuple(
        _project_asset(component)
        for component in components
        if isinstance(component, dict) and component.get("type") == CRYPTO_ASSET_TYPE
    )
    return CryptoInventory(assets=assets)
