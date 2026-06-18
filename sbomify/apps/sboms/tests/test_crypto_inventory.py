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
    assert ecdsa.curve == "secp384r1"  # 1.7 uses ellipticCurve
    assert ecdsa.algorithm_family == "ecdsa"
    mldsa = _by_name(inv, "ML-DSA-65")
    assert mldsa.algorithm_family == "ml-dsa"
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
