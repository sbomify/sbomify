"""Tests for the post-quantum (PQC) readiness classification (#1001 increment 4).

The classification table is grounded in NIST guidance (FIPS 203/204/205, draft 206,
NIST IR 8547, NSA CNSA 2.0) and adversarially verified. Key, sometimes
counter-intuitive, decisions encoded here:

- SHA-256 is SAFE (Grover does not speed up collision search; NIST keeps SHA-2
  approved) — NOT "review".
- ``nistQuantumSecurityLevel`` is a NIST strength-category floor, not a quantum-safe
  flag: algorithm identity decides the verdict; the declared level only raises a
  data-quality flag when it looks mislabeled.
"""

from __future__ import annotations

import pytest

from sbomify.apps.sboms.crypto_inventory import CryptoAsset, CryptoInventory
from sbomify.apps.sboms.pqc import (
    PqcStatus,
    assess_inventory,
    classify_crypto_asset,
)


def _algo(name: str | None, **kw) -> CryptoAsset:
    return CryptoAsset(name=name, bom_ref=None, oid=None, asset_type="algorithm", **kw)


# --- standardized PQC -> SAFE -------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["ML-KEM-768", "Kyber768", "CRYSTALS-Kyber", "ML-DSA-65", "Dilithium3", "SLH-DSA-SHA2-128s", "SPHINCS+"],
)
def test_standardized_pqc_is_safe(name):
    assert classify_crypto_asset(_algo(name)).status is PqcStatus.SAFE


# --- quantum-vulnerable asymmetric -> VULNERABLE ------------------------------


@pytest.mark.parametrize(
    "name",
    ["RSA-2048", "ECDSA-P256", "Ed25519", "Ed448", "X25519", "DH-2048", "ECDH-P384", "DSA", "ElGamal"],
)
def test_shor_breakable_asymmetric_is_vulnerable(name):
    assert classify_crypto_asset(_algo(name)).status is PqcStatus.VULNERABLE


def test_ecdsa_recognized_via_algorithm_family_1_7():
    assert classify_crypto_asset(_algo(None, algorithm_family="ECDSA")).status is PqcStatus.VULNERABLE


def test_elliptic_curve_recognized_via_curve_field():
    asset = _algo(None, primitive="signature", curve="secp256r1")
    assert classify_crypto_asset(asset).status is PqcStatus.VULNERABLE


# --- symmetric / hash (size-dependent) ---------------------------------------


def test_aes_256_is_safe():
    assert classify_crypto_asset(_algo("AES-256-GCM")).status is PqcStatus.SAFE


def test_aes_128_is_review():
    assert classify_crypto_asset(_algo("AES-128-CBC")).status is PqcStatus.REVIEW


def test_aes_without_key_size_is_review():
    assert classify_crypto_asset(_algo("AES")).status is PqcStatus.REVIEW


def test_chacha20_is_safe():
    assert classify_crypto_asset(_algo("ChaCha20-Poly1305")).status is PqcStatus.SAFE


def test_sha256_is_safe_not_review():
    # Adversarially verified: Grover does not attack collision resistance; NIST keeps SHA-2 approved.
    assert classify_crypto_asset(_algo("SHA-256")).status is PqcStatus.SAFE


def test_sha512_is_safe():
    assert classify_crypto_asset(_algo("SHA-512")).status is PqcStatus.SAFE


@pytest.mark.parametrize("name", ["MD5", "SHA-1"])
def test_classically_broken_hash_is_review(name):
    assert classify_crypto_asset(_algo(name)).status is PqcStatus.REVIEW


# --- gray zone -> REVIEW ------------------------------------------------------


@pytest.mark.parametrize("name", ["3DES", "TripleDES", "Falcon-512", "FN-DSA", "HQC-128"])
def test_gray_zone_is_review(name):
    assert classify_crypto_asset(_algo(name)).status is PqcStatus.REVIEW


# --- unknown ------------------------------------------------------------------


def test_unrecognized_algorithm_is_unknown():
    assert classify_crypto_asset(_algo("FooCipher9000")).status is PqcStatus.UNKNOWN


def test_certificate_without_algorithm_info_is_unknown():
    cert = CryptoAsset(name="server-cert", bom_ref=None, oid=None, asset_type="certificate")
    assert classify_crypto_asset(cert).status is PqcStatus.UNKNOWN


# --- declared nistQuantumSecurityLevel = corroborating / data-quality only -----


def test_vulnerable_family_with_declared_pqc_level_flags_mislabel_but_stays_vulnerable():
    asset = _algo("RSA-2048", nist_quantum_security_level=3)
    result = classify_crypto_asset(asset)
    assert result.status is PqcStatus.VULNERABLE  # identity wins, not the integer
    assert result.data_quality_flag is not None


def test_pqc_family_declared_level_zero_flags_data_quality_but_stays_safe():
    asset = _algo("ML-KEM-768", nist_quantum_security_level=0)
    result = classify_crypto_asset(asset)
    assert result.status is PqcStatus.SAFE
    assert result.data_quality_flag is not None


def test_unrecognized_with_declared_pqc_level_is_review_not_safe():
    # The integer alone must never assert SAFE on an unrecognized algorithm.
    asset = _algo("MysteryKEM", nist_quantum_security_level=5)
    assert classify_crypto_asset(asset).status is PqcStatus.REVIEW


# --- inventory summary --------------------------------------------------------


def _inv(*assets: CryptoAsset) -> CryptoInventory:
    return CryptoInventory(assets=tuple(assets))


def test_summary_at_risk_when_any_vulnerable():
    summary = assess_inventory(_inv(_algo("RSA-2048"), _algo("ML-KEM-768"), _algo("AES-256")))
    assert summary.overall == "at_risk"
    assert summary.counts[PqcStatus.VULNERABLE.value] == 1
    assert summary.counts[PqcStatus.SAFE.value] == 2
    assert len(summary.results) == 3


def test_summary_ready_when_all_safe():
    summary = assess_inventory(_inv(_algo("ML-KEM-768"), _algo("AES-256"), _algo("SHA-512")))
    assert summary.overall == "ready"


def test_summary_needs_review_when_review_present_no_vulnerable():
    summary = assess_inventory(_inv(_algo("ML-KEM-768"), _algo("AES-128")))
    assert summary.overall == "needs_review"


def test_summary_needs_review_for_unclassifiable_algorithm():
    summary = assess_inventory(_inv(_algo("ML-KEM-768"), _algo("FooCipher9000")))
    assert summary.overall == "needs_review"


def test_summary_not_assessed_when_no_classifiable_assets():
    summary = assess_inventory(_inv())
    assert summary.overall == "not_assessed"
