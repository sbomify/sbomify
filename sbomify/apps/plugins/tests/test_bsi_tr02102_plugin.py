"""Tests for the BSI TR-02102 crypto-mechanisms assessment plugin."""

from __future__ import annotations

import json
from pathlib import Path

from sbomify.apps.plugins.builtins.bsi_tr02102 import BsiTr02102Plugin
from sbomify.apps.plugins.sdk import AssessmentCategory


def _crypto(name: str, asset_type: str = "algorithm", **algo) -> dict:
    comp = {
        "type": "cryptographic-asset",
        "name": name,
        "bom-ref": name.lower(),
        "cryptoProperties": {"assetType": asset_type},
    }
    if algo:
        comp["cryptoProperties"]["algorithmProperties"] = algo
    return comp


def _protocol(name: str, proto_type: str, version: str) -> dict:
    return {
        "type": "cryptographic-asset",
        "name": name,
        "bom-ref": name.lower(),
        "cryptoProperties": {
            "assetType": "protocol",
            "protocolProperties": {"type": proto_type, "version": version},
        },
    }


def _cbom(*components: dict) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "components": list(components)}


def _assess(doc: dict, tmp_path: Path):
    path = tmp_path / "cbom.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return BsiTr02102Plugin().assess("test-sbom-id", path)


def _one(component: dict, tmp_path: Path):
    return _assess(_cbom(component), tmp_path).findings[0]


def test_metadata_runs_on_cbom_and_sbom():
    metadata = BsiTr02102Plugin().get_metadata()
    assert metadata.name == "bsi-tr02102"
    assert metadata.category is AssessmentCategory.COMPLIANCE
    assert metadata.supported_bom_types == ["cbom", "sbom"]


def test_rsa_3000_bit_floor(tmp_path: Path):
    # BSI requires 3000-bit moduli; RSA-2048 fails here while SP 800-131A only warns.
    assert _one(_crypto("RSA-2048"), tmp_path).status == "fail"
    assert _one(_crypto("RSA-3072"), tmp_path).status == "pass"

    unsized = _one(_crypto("RSA"), tmp_path)
    assert unsized.status == "info"


def test_ecc_250_bit_floor(tmp_path: Path):
    assert _one(_crypto("ECDSA", curve="P-224"), tmp_path).status == "fail"
    assert _one(_crypto("ECDSA", curve="P-256"), tmp_path).status == "pass"
    assert _one(_crypto("ECDH", curve="brainpoolP320r1"), tmp_path).status == "pass"


def test_block_cipher_modes(tmp_path: Path):
    assert _one(_crypto("AES-128-GCM"), tmp_path).status == "pass"
    assert _one(_crypto("AES-256", mode="ecb"), tmp_path).status == "fail"
    assert _one(_crypto("AES-256", mode="cbc"), tmp_path).status == "warning"


def test_hashes(tmp_path: Path):
    assert _one(_crypto("SHA-256"), tmp_path).status == "pass"
    assert _one(_crypto("SHA-1"), tmp_path).status == "fail"
    assert _one(_crypto("SHA-224"), tmp_path).status == "fail"


def test_legacy_ciphers_fail(tmp_path: Path):
    assert _one(_crypto("3DES"), tmp_path).status == "fail"
    assert _one(_crypto("DES"), tmp_path).status == "fail"
    assert _one(_crypto("RC4"), tmp_path).status == "fail"


def test_pqc_recommendations_include_frodo_and_mceliece(tmp_path: Path):
    # BSI recommends FrodoKEM and Classic McEliece, unlike NIST.
    assert _one(_crypto("ML-KEM-768"), tmp_path).status == "pass"
    assert _one(_crypto("FrodoKEM-976"), tmp_path).status == "pass"
    assert _one(_crypto("Classic-McEliece"), tmp_path).status == "pass"


def test_chacha_is_out_of_scope_info(tmp_path: Path):
    finding = _one(_crypto("ChaCha20-Poly1305"), tmp_path)
    assert finding.status == "info"


def test_tls_versions(tmp_path: Path):
    assert _one(_protocol("legacy-tls", "tls", "1.0"), tmp_path).status == "fail"
    tls12 = _one(_protocol("tls12", "tls", "1.2"), tmp_path)
    assert tls12.status == "warning"
    assert _one(_protocol("tls13", "tls", "1.3"), tmp_path).status == "pass"


def test_non_tls_protocol_not_assessed(tmp_path: Path):
    finding = _one(_protocol("ssh-server", "ssh", "2"), tmp_path)
    assert finding.status == "info"
    assert "not assessed" in finding.description.lower()


def test_certificate_asset_not_assessed(tmp_path: Path):
    finding = _one(_crypto("server-cert", asset_type="certificate"), tmp_path)
    assert finding.status == "info"


def test_crypto_free_document_skips_quietly(tmp_path: Path):
    result = _assess(_cbom(), tmp_path)
    assert result.metadata and result.metadata.get("skipped") is True


def test_result_serializes_to_json(tmp_path: Path):
    result = _assess(_cbom(_crypto("RSA-2048")), tmp_path)
    payload = json.dumps(result.to_dict())
    assert json.loads(payload)["category"] == "compliance"
