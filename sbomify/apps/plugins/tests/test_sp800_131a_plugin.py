"""Tests for the NIST SP 800-131A legacy-algorithm transitions plugin."""

from __future__ import annotations

import json
from pathlib import Path

from sbomify.apps.plugins.builtins.sp800_131a import Sp800131aPlugin
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
    return Sp800131aPlugin().assess("test-sbom-id", path)


def _one(doc_component: dict, tmp_path: Path):
    return _assess(_cbom(doc_component), tmp_path).findings[0]


def test_metadata_runs_on_cbom_and_sbom():
    metadata = Sp800131aPlugin().get_metadata()
    assert metadata.name == "nist-sp800-131a"
    assert metadata.category is AssessmentCategory.COMPLIANCE
    assert metadata.supported_bom_types == ["cbom", "sbom"]
    assert metadata.requires_crypto_assets is True


def test_never_approved_algorithms_fail(tmp_path: Path):
    result = _assess(
        _cbom(_crypto("DES"), _crypto("RC4"), _crypto("MD5"), _crypto("Skipjack")),
        tmp_path,
    )
    assert result.summary.fail_count == 4
    for finding in result.findings:
        assert finding.status == "fail"
        assert finding.remediation


def test_3des_encryption_fails_but_decrypt_only_is_legacy_warning(tmp_path: Path):
    encrypt = _one(_crypto("3DES", cryptoFunctions=["encrypt", "decrypt"]), tmp_path)
    assert encrypt.status == "fail"

    decrypt_only = _one(_crypto("DES-EDE3", cryptoFunctions=["decrypt"]), tmp_path)
    assert decrypt_only.status == "warning"
    assert "legacy" in decrypt_only.description.lower()


def test_sha1_signature_generation_fails_other_use_deprecated(tmp_path: Path):
    signing = _one(_crypto("SHA-1", cryptoFunctions=["sign"]), tmp_path)
    assert signing.status == "fail"

    digest = _one(_crypto("SHA-1", cryptoFunctions=["digest"]), tmp_path)
    assert digest.status == "warning"
    assert "2030" in digest.description

    hmac = _one(_crypto("HMAC-SHA1"), tmp_path)
    assert hmac.status == "warning"
    assert "2030" in hmac.description


def test_sha224_family_deprecated_sha256_approved(tmp_path: Path):
    assert _one(_crypto("SHA-224"), tmp_path).status == "warning"
    assert _one(_crypto("SHA3-224"), tmp_path).status == "warning"
    assert _one(_crypto("SHA-256"), tmp_path).status == "pass"
    assert _one(_crypto("SHA-384"), tmp_path).status == "pass"


def test_rsa_strength_thresholds(tmp_path: Path):
    assert _one(_crypto("RSA-1024"), tmp_path).status == "fail"
    at_112 = _one(_crypto("RSA", parameterSetIdentifier="2048"), tmp_path)
    assert at_112.status == "warning"
    assert "2030" in at_112.description
    assert _one(_crypto("RSA-3072"), tmp_path).status == "pass"
    # Signature hash must not be read as the modulus size.
    assert _one(_crypto("RSA-3072-SHA-256"), tmp_path).status == "pass"

    unsized = _one(_crypto("RSA"), tmp_path)
    assert unsized.status == "info"
    assert "size" in unsized.description.lower()


def test_ecc_curve_strength_thresholds(tmp_path: Path):
    assert _one(_crypto("ECDSA", curve="P-192"), tmp_path).status == "fail"
    assert _one(_crypto("ECDSA", curve="P-224"), tmp_path).status == "warning"
    assert _one(_crypto("ECDSA", curve="P-256"), tmp_path).status == "pass"
    assert _one(_crypto("ECDH", curve="secp163k1"), tmp_path).status == "fail"
    assert _one(_crypto("Ed25519"), tmp_path).status == "pass"


def test_plain_dsa_signing_removed_verify_only_legacy(tmp_path: Path):
    assert _one(_crypto("DSA", cryptoFunctions=["sign"]), tmp_path).status == "fail"
    assert _one(_crypto("DSA"), tmp_path).status == "fail"
    verify_only = _one(_crypto("DSA", cryptoFunctions=["verify"]), tmp_path)
    assert verify_only.status == "warning"


def test_pqc_names_pass_and_do_not_hit_dsa_rule(tmp_path: Path):
    assert _one(_crypto("ML-DSA-65"), tmp_path).status == "pass"
    assert _one(_crypto("ML-KEM-768"), tmp_path).status == "pass"
    assert _one(_crypto("AES-128-GCM"), tmp_path).status == "pass"


def test_non_nist_and_unrecognized_are_info(tmp_path: Path):
    chacha = _one(_crypto("ChaCha20-Poly1305"), tmp_path)
    assert chacha.status == "info"
    assert "scope" in chacha.description.lower()

    unknown = _one(_crypto("FrobnicatorCipher"), tmp_path)
    assert unknown.status == "info"


def test_non_algorithm_asset_not_assessed_unless_name_identifies_algorithm(tmp_path: Path):
    cert = _one(_crypto("server-cert", asset_type="certificate"), tmp_path)
    assert cert.status == "info"
    assert "not assessed" in cert.title.lower()

    named = _one(_crypto("MD5-signing-cert", asset_type="certificate"), tmp_path)
    assert named.status == "fail"


def test_summary_counts_sum_to_total(tmp_path: Path):
    result = _assess(
        _cbom(_crypto("MD5"), _crypto("SHA-224"), _crypto("AES-256"), _crypto("mystery")),
        tmp_path,
    )
    summary = result.summary
    assert (
        summary.pass_count + summary.fail_count + summary.warning_count + summary.error_count + summary.info_count
        == summary.total_findings
        == 4
    )


def test_assess_crypto_free_document_is_skipped_quietly(tmp_path: Path):
    # pqc-readiness alone owns the empty-CBOM misfire warning; this plugin
    # skips quietly so an empty CBOM does not stack one warning per plugin.
    result = _assess(_cbom(), tmp_path)
    assert result.summary.total_findings == 1
    assert result.findings[0].status == "info"
    assert result.metadata and result.metadata.get("skipped") is True


def test_assess_invalid_json_returns_error_not_raise(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    result = Sp800131aPlugin().assess("test-sbom-id", path)
    assert result.summary.error_count == 1
    assert result.findings[0].status == "error"


def test_result_serializes_to_json(tmp_path: Path):
    result = _assess(_cbom(_crypto("MD5")), tmp_path)
    payload = json.dumps(result.to_dict())
    assert json.loads(payload)["category"] == "compliance"
