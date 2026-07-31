"""Tests for the CBOM crypto-asset inventory derivation (#1001 increment 1)."""

import json
from pathlib import Path

from sbomify.apps.sboms.crypto_inventory import CryptoAsset, CryptoInventory, derive_crypto_inventory

_DATA = Path(__file__).parent / "test_data"


def _load(name: str) -> dict:
    return json.loads((_DATA / name).read_text())


def _by_name(inv: CryptoInventory, name: str) -> CryptoAsset:
    return next(a for a in inv.assets if a.name == name)


def test_derives_crypto_assets_from_cbom_1_6():
    inv = derive_crypto_inventory(_load("cbom_sample_1.6.cdx.json"))
    assert isinstance(inv, CryptoInventory)
    # 6 cryptographic-asset components; the plain library is excluded
    assert inv.count == 6
    assert all(isinstance(a, CryptoAsset) for a in inv.assets)
    assert "left-pad" not in {a.name for a in inv.assets}
    # asset-type breakdown (algorithm x3, certificate, protocol; broken entry -> None)
    assert inv.by_asset_type.get("algorithm") == 3
    assert inv.by_asset_type.get("certificate") == 1
    assert inv.by_asset_type.get("protocol") == 1


def test_projects_algorithm_fields_1_6():
    inv = derive_crypto_inventory(_load("cbom_sample_1.6.cdx.json"))
    rsa = _by_name(inv, "RSA-2048")
    assert rsa.asset_type == "algorithm"
    assert rsa.bom_ref == "crypto-rsa2048"
    assert rsa.oid == "1.2.840.113549.1.1.1"
    assert rsa.primitive == "pke"
    assert rsa.parameter_set == "2048"
    assert rsa.nist_quantum_security_level == 0
    assert "encrypt" in rsa.crypto_functions

    ecdsa = _by_name(inv, "ECDSA-P256")
    assert ecdsa.primitive == "signature"
    assert ecdsa.curve == "secp256r1"

    mlkem = _by_name(inv, "ML-KEM-768")
    assert mlkem.primitive == "kem"
    assert mlkem.nist_quantum_security_level == 3


def test_projects_certificate_and_protocol_1_6():
    inv = derive_crypto_inventory(_load("cbom_sample_1.6.cdx.json"))
    cert = _by_name(inv, "server-cert")
    assert cert.asset_type == "certificate"
    assert cert.certificate and cert.certificate.get("subjectName") == "CN=demo.example.com"

    proto = _by_name(inv, "TLS")
    assert proto.asset_type == "protocol"
    assert proto.protocol and proto.protocol.get("version") == "1.3"


def test_tolerates_missing_crypto_properties():
    inv = derive_crypto_inventory(_load("cbom_sample_1.6.cdx.json"))
    broken = _by_name(inv, "broken-entry")
    assert broken.asset_type is None
    assert broken.primitive is None  # no crash


def test_1_7_field_aliases_elliptic_curve_and_family():
    inv = derive_crypto_inventory(_load("cbom_sample_1.7.cdx.json"))
    assert inv.count == 2
    ecdsa = _by_name(inv, "ECDSA-P384")
    assert ecdsa.curve == "nist/P-384"  # 1.7 uses ellipticCurve (registry-namespaced)
    assert ecdsa.algorithm_family == "ECDSA"
    mldsa = _by_name(inv, "ML-DSA-65")
    assert mldsa.algorithm_family == "ML-DSA"
    assert mldsa.primitive == "signature"


def test_non_crypto_sbom_yields_empty_inventory():
    inv = derive_crypto_inventory(_load("sbomify_syft.cdx.json"))
    assert inv.count == 0
    assert inv.assets == ()


def test_handles_empty_or_missing_components():
    assert derive_crypto_inventory({}).count == 0
    assert derive_crypto_inventory({"components": []}).count == 0


def test_malformed_field_types_never_raise_and_stay_schema_clean():
    """Garbage field types must not raise (incl. by_asset_type's Counter) nor break the str|None API schema."""
    doc = {
        "components": [
            {
                "type": "cryptographic-asset",
                "name": ["not", "a", "string"],
                "cryptoProperties": {
                    "assetType": {"nested": "dict"},  # unhashable -> would break Counter
                    "algorithmProperties": {
                        "primitive": ["list"],  # non-str on a str field
                        "parameterSetIdentifier": 768,  # scalar -> coerced to "768"
                        "cryptoFunctions": ["keygen", {"x": 1}],  # mixed -> only str-able kept
                    },
                },
            }
        ]
    }
    inv = derive_crypto_inventory(doc)
    assert inv.count == 1
    assert inv.by_asset_type == {}  # non-string assetType dropped, no TypeError
    asset = inv.assets[0]
    assert asset.asset_type is None
    assert asset.name is None  # non-string dropped
    assert asset.primitive is None  # list dropped
    assert asset.parameter_set == "768"  # scalar coerced to str
    assert all(isinstance(f, str) for f in asset.crypto_functions)


def test_derives_from_legacy_ibm_cbom_1_0():
    """The pre-standard IBM CBOM lineage (CycloneDX 1.4 fork, ``crypto-asset``
    type, ``variant``/``implementationLevel`` spellings, root-level security
    levels) inventories with its fields mapped onto the 1.6 projection."""
    inv = derive_crypto_inventory(_load("cbom_sample_legacy_1.0.cdx.json"))
    assert inv.count == 2  # the plain library and the non-crypto metadata.component are excluded
    aes = _by_name(inv, "AES")
    assert aes.asset_type == "algorithm"
    assert aes.parameter_set == "AES-128-GCM"  # legacy "variant"
    assert aes.execution_environment == "softwarePlainRam"  # legacy "implementationLevel"
    assert aes.classical_security_level == 128  # legacy root-level placement
    assert aes.nist_quantum_security_level == 1
    assert aes.mode == "gcm"
    assert aes.implementation_platform == "x86_64"
    assert aes.certification_level == ("none",)  # legacy bare string -> tuple
    dilithium = _by_name(inv, "Dilithium")
    assert dilithium.primitive == "signature"
    assert dilithium.nist_quantum_security_level == 5


def test_untyped_component_with_crypto_properties_is_included():
    doc = {"components": [{"type": "library", "name": "openssl-shim", "cryptoProperties": {"assetType": "algorithm"}}]}
    inv = derive_crypto_inventory(doc)
    assert inv.count == 1
    assert inv.assets[0].asset_type == "algorithm"


def test_metadata_component_crypto_asset_is_inventoried():
    meta_asset = {
        "type": "cryptographic-asset",
        "bom-ref": "root-alg",
        "name": "RootAlg",
        "cryptoProperties": {"assetType": "algorithm"},
    }
    doc = {"metadata": {"component": meta_asset}, "components": []}
    assert derive_crypto_inventory(doc).count == 1
    # Listed again under components with the same bom-ref -> not double-counted.
    doc["components"] = [dict(meta_asset)]
    assert derive_crypto_inventory(doc).count == 1


def test_detection_and_inventory_agree_on_every_lineage():
    """Every lineage inventories non-empty; only pure CBOMs re-tag. A document
    tagged cbom therefore never renders an empty inventory, and mixed
    documents keep their sbom pipelines while still deriving crypto."""
    from sbomify.apps.sboms.utils import _is_cbom

    for fixture in ("cbom_sample_legacy_1.0.cdx.json", "cbom_sample_1.6.cdx.json", "cbom_sample_1.7.cdx.json"):
        assert derive_crypto_inventory(_load(fixture)).count > 0, fixture
    assert _is_cbom(_load("cbom_sample_1.7.cdx.json"))  # every component crypto -> pure
    assert not _is_cbom(_load("cbom_sample_1.6.cdx.json"))  # left-pad rides along -> mixed, stays sbom
    assert not _is_cbom(_load("cbom_sample_legacy_1.0.cdx.json"))  # legacy doc is mixed too
    # A pure CBOM whose sole crypto asset is metadata.component still re-tags.
    meta_only = {"metadata": {"component": {"type": "crypto-asset", "cryptoProperties": {"assetType": "algorithm"}}}}
    assert _is_cbom(meta_only)
    assert derive_crypto_inventory(meta_only).count == 1
    plain = _load("sbomify_syft.cdx.json")
    assert not _is_cbom(plain)
    assert derive_crypto_inventory(plain).count == 0


def test_registry_normalization_folds_curve_spellings():
    """The acceptance case for registry normalization: a 1.6 document naming
    prime256v1 and a 1.7 document naming nist/P-256 inventory identically."""
    doc = {
        "components": [
            {
                "type": "cryptographic-asset",
                "name": "ECDSA-old-spelling",
                "cryptoProperties": {"assetType": "algorithm", "algorithmProperties": {"curve": "prime256v1"}},
            },
            {
                "type": "cryptographic-asset",
                "name": "ECDSA-registry",
                "cryptoProperties": {
                    "assetType": "algorithm",
                    "algorithmProperties": {"algorithmFamily": "ECDSA", "ellipticCurve": "nist/P-256"},
                },
            },
            {
                "type": "cryptographic-asset",
                "name": "ECDSA-secg",
                "cryptoProperties": {"assetType": "algorithm", "algorithmProperties": {"curve": "secp256r1"}},
            },
        ]
    }
    inv = derive_crypto_inventory(doc)
    normalized = {a.normalized_curve for a in inv.assets}
    assert normalized == {"nist/P-256"}
    registry = _by_name(inv, "ECDSA-registry")
    assert registry.normalized_family == "ECDSA"
    assert not registry.registry_unrecognized


def test_registry_unknown_names_pass_through_flagged():
    doc = {
        "components": [
            {
                "type": "cryptographic-asset",
                "name": "HomeGrown",
                "cryptoProperties": {
                    "assetType": "algorithm",
                    "algorithmProperties": {"curve": "curve9000", "algorithmFamily": "NotARealFamily"},
                },
            }
        ]
    }
    asset = derive_crypto_inventory(doc).assets[0]
    assert asset.curve == "curve9000"  # raw value kept
    assert asset.normalized_curve is None
    assert asset.registry_unrecognized


def test_registry_normalizes_curve_from_oid():
    doc = {
        "components": [
            {
                "type": "cryptographic-asset",
                "name": "some-ec-key",
                "cryptoProperties": {"assetType": "relatedCryptoMaterial", "oid": "1.2.840.10045.3.1.7"},
            }
        ]
    }
    assert derive_crypto_inventory(doc).assets[0].normalized_curve == "nist/P-256"


def test_related_asset_refs_resolve_to_edges():
    """Deprecated 1.6 refs and 1.7 relatedCryptographicAssets both become
    typed edges, resolved against the inventory's bom-refs."""
    doc = {
        "components": [
            {
                "type": "cryptographic-asset",
                "bom-ref": "alg-rsa",
                "name": "RSA-2048",
                "cryptoProperties": {"assetType": "algorithm"},
            },
            {
                "type": "cryptographic-asset",
                "bom-ref": "cert-1",
                "name": "server-cert",
                "cryptoProperties": {
                    "assetType": "certificate",
                    "certificateProperties": {
                        "signatureAlgorithmRef": "alg-rsa",
                        "subjectPublicKeyRef": "missing-key",
                    },
                },
            },
            {
                "type": "cryptographic-asset",
                "bom-ref": "proto-tls",
                "name": "TLS",
                "cryptoProperties": {
                    "assetType": "protocol",
                    "protocolProperties": {
                        "cryptoRefArray": ["alg-rsa"],
                        "relatedCryptographicAssets": [{"type": "algorithm", "ref": "alg-rsa"}],
                    },
                },
            },
        ]
    }
    inv = derive_crypto_inventory(doc)
    edges = {(e.source, e.relation, e.target, e.resolved) for e in inv.edges}
    assert ("cert-1", "signatureAlgorithm", "alg-rsa", True) in edges
    assert ("cert-1", "subjectPublicKey", "missing-key", False) in edges  # dangling ref stays visible
    assert ("proto-tls", "cryptoRef", "alg-rsa", True) in edges
    assert ("proto-tls", "algorithm", "alg-rsa", True) in edges  # 1.7 relatedCryptographicAssets


def test_registry_build_tables_skips_malformed_entries():
    from sbomify.apps.sboms.crypto_registry import build_tables

    tables = build_tables(
        {
            "algorithms": [{"family": "AES"}, {"nofamily": True}, "junk"],
            "ellipticCurves": [
                {"name": "nist", "curves": [{"name": "P-256", "oid": "1.2.840.10045.3.1.7", "aliases": []}]},
                {"name": "bad", "curves": [{"oid": "1.2.3"}, "junk", {"name": 42}]},
                "junk",
            ],
        }
    )
    assert tables.family_by_name == {"aes": "AES"}
    assert tables.curve_by_name["p-256"] == "nist/P-256"
    assert tables.curve_by_oid == {"1.2.840.10045.3.1.7": "nist/P-256"}
