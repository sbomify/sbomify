"""Tests for the CNSA 2.0 compliance assessment plugin."""

from __future__ import annotations

import json
from pathlib import Path

from sbomify.apps.plugins.builtins.cnsa2 import Cnsa2Plugin
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


def _cbom(*components: dict) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "components": list(components)}


def _assess(doc: dict, tmp_path: Path):
    path = tmp_path / "cbom.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return Cnsa2Plugin().assess("test-sbom-id", path)


def _one(component: dict, tmp_path: Path):
    return _assess(_cbom(component), tmp_path).findings[0]


def test_metadata_runs_on_cbom_and_sbom():
    metadata = Cnsa2Plugin().get_metadata()
    assert metadata.name == "cnsa-2.0"
    assert metadata.category is AssessmentCategory.COMPLIANCE
    assert metadata.supported_bom_types == ["cbom", "sbom"]


def test_cnsa2_allow_list_passes(tmp_path: Path):
    assert _one(_crypto("AES-256-GCM"), tmp_path).status == "pass"
    assert _one(_crypto("SHA-384"), tmp_path).status == "pass"
    assert _one(_crypto("ML-KEM-1024"), tmp_path).status == "pass"
    assert _one(_crypto("ML-DSA-87"), tmp_path).status == "pass"
    assert _one(_crypto("LMS-SHA-256"), tmp_path).status == "pass"
    assert _one(_crypto("XMSS"), tmp_path).status == "pass"


def test_undersized_parameters_fail(tmp_path: Path):
    assert _one(_crypto("AES-128"), tmp_path).status == "fail"
    assert _one(_crypto("SHA-256"), tmp_path).status == "fail"
    assert _one(_crypto("ML-KEM-768"), tmp_path).status == "fail"
    assert _one(_crypto("ML-DSA-65"), tmp_path).status == "fail"


def test_slh_dsa_not_in_cnsa(tmp_path: Path):
    assert _one(_crypto("SLH-DSA-SHA2-128s"), tmp_path).status == "fail"


def test_cnsa1_holdovers_warn_with_transition_deadline(tmp_path: Path):
    rsa = _one(_crypto("RSA-3072"), tmp_path)
    assert rsa.status == "warning"
    assert "2033" in rsa.description

    p384 = _one(_crypto("ECDSA", curve="P-384"), tmp_path)
    assert p384.status == "warning"


def test_weak_classical_parameters_fail(tmp_path: Path):
    assert _one(_crypto("RSA-2048"), tmp_path).status == "fail"
    assert _one(_crypto("ECDSA", curve="P-256"), tmp_path).status == "fail"
    assert _one(_crypto("Ed25519"), tmp_path).status == "fail"
    assert _one(_crypto("MD5"), tmp_path).status == "fail"


def test_unrecognized_and_non_algorithm_are_info(tmp_path: Path):
    assert _one(_crypto("FrobnicatorCipher"), tmp_path).status == "info"
    cert = _one(_crypto("server-cert", asset_type="certificate"), tmp_path)
    assert cert.status == "info"


def test_crypto_free_document_skips_quietly(tmp_path: Path):
    result = _assess(_cbom(), tmp_path)
    assert result.metadata and result.metadata.get("skipped") is True


def test_result_serializes_to_json(tmp_path: Path):
    result = _assess(_cbom(_crypto("AES-256")), tmp_path)
    payload = json.dumps(result.to_dict())
    assert json.loads(payload)["category"] == "compliance"
