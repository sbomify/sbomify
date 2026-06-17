"""Post-quantum (PQC) readiness classification for crypto assets.

Classifies a :class:`~sbomify.apps.sboms.crypto_inventory.CryptoAsset` as
quantum-safe, quantum-vulnerable, needs-review, or unknown, and aggregates an
inventory into an overall readiness verdict.

The table is grounded in NIST guidance — FIPS 203 (ML-KEM), 204 (ML-DSA),
205 (SLH-DSA), draft 206 (FN-DSA/Falcon), NIST IR 8547, and NSA CNSA 2.0 — and
was adversarially verified. Notable, sometimes counter-intuitive, rules:

- Standardized PQC (ML-KEM/ML-DSA/SLH-DSA, incl. legacy names Kyber/Dilithium/
  SPHINCS+) is SAFE. Selected-but-not-yet-finalized PQC (FN-DSA/Falcon, HQC) and
  stateful special-use schemes (XMSS/LMS) are REVIEW.
- Shor-breakable public-key crypto (RSA, DSA, DH, ECDH, ECDSA, EdDSA incl.
  Ed25519/Ed448, X25519/X448, ElGamal, any EC) is VULNERABLE.
- Symmetric/hash are only Grover-weakened, not broken: AES-192/256, ChaCha20,
  SHA-256/384/512, SHA-3 are SAFE; **SHA-256 is SAFE — Grover does not attack
  collision resistance and NIST keeps SHA-2 approved**. AES-128 (~64-bit
  post-Grover), 3DES (withdrawn; legacy-decrypt only) and bare/unsized symmetric
  are REVIEW. MD5/SHA-1 are classically broken -> REVIEW.
- ``nistQuantumSecurityLevel`` is a NIST *strength-category floor*, not a
  quantum-safe flag. Algorithm identity decides the verdict; the declared level
  only raises a ``data_quality_flag`` when it looks mislabeled, and never on its
  own asserts SAFE for an unrecognized algorithm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from sbomify.apps.sboms.crypto_inventory import CryptoAsset, CryptoInventory


class PqcStatus(str, Enum):
    SAFE = "quantum_safe"
    VULNERABLE = "quantum_vulnerable"
    REVIEW = "review"
    UNKNOWN = "unknown"


# Overall inventory readiness verdicts.
OVERALL_AT_RISK = "at_risk"
OVERALL_NEEDS_REVIEW = "needs_review"
OVERALL_READY = "ready"
OVERALL_NOT_ASSESSED = "not_assessed"


@dataclass(frozen=True)
class PqcAssessment:
    status: PqcStatus
    family: str | None
    reason: str
    data_quality_flag: str | None = None


@dataclass(frozen=True)
class PqcResult:
    asset: CryptoAsset
    assessment: PqcAssessment


@dataclass(frozen=True)
class PqcSummary:
    overall: str
    counts: dict[str, int]
    results: tuple[PqcResult, ...]


# Substrings distinctive enough to match once the PQC families have been ruled
# out first (e.g. "dsa" here only reaches ECDSA/DSA/EdDSA, since ML-DSA/SLH-DSA/
# FN-DSA are matched earlier).
_VULNERABLE_SUBSTRINGS = (
    "rsa",
    "ecdsa",
    "eddsa",
    "ed25519",
    "ed448",
    "ecdh",
    "x25519",
    "x448",
    "elgamal",
    "ecmqv",
    "ecies",
    "diffie",
    "hellman",
    "ffdh",
    "dsa",
    "secp",
    "sect",
    "brainpool",
    "prime256v1",
    "curve25519",
    "curve448",
    "nistp",
)
# Short tokens matched whole to avoid false positives.
_VULNERABLE_TOKENS = frozenset({"dh", "dhe", "ec", "ecc", "mqv", "p-256", "p-384", "p-521", "p256", "p384", "p521"})

_PQC_SAFE_SUBSTRINGS = ("ml-kem", "mlkem", "kyber", "ml-dsa", "mldsa", "dilithium", "slh-dsa", "slhdsa", "sphincs")
# PQC-adjacent but not a finalized FIPS standard, or stateful special-use.
_PQC_REVIEW_SUBSTRINGS = (
    "fn-dsa",
    "falcon",
    "hqc",
    "bike",
    "mceliece",
    "frodo",
    "ntru",
    "saber",
    "xmss",
    "lms",
    "hss",
)


def _haystack(asset: CryptoAsset) -> str:
    parts = [asset.name, asset.algorithm_family, asset.curve]
    return " ".join(p for p in parts if isinstance(p, str)).lower()


def _tokens(haystack: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", haystack))


def _classify_symmetric_or_hash(hay: str) -> tuple[PqcStatus, str, str] | None:
    """Symmetric ciphers and hashes (Grover-weakened, not Shor-broken), or None."""
    if "md5" in hay or re.search(r"sha-?1(?![0-9])", hay):
        return PqcStatus.REVIEW, "broken-hash", "Classically broken (collisions) — remediate regardless of quantum"
    if any(t in hay for t in ("3des", "triple-des", "tripledes", "tdea", "des-ede", "des3")):
        return PqcStatus.REVIEW, "3DES", "Withdrawn (SP 800-67); legacy decrypt only — review usage"
    if "aes" in hay:
        if "256" in hay or "192" in hay:
            return PqcStatus.SAFE, "AES", "Grover-resistant at >=192-bit keys"
        if "128" in hay:
            return PqcStatus.REVIEW, "AES-128", "~64-bit post-Grover; below the CNSA 2.0 256-bit bar — review"
        return PqcStatus.REVIEW, "AES", "Key size unspecified — AES-128 and AES-256 differ; review"
    if "chacha" in hay:
        return PqcStatus.SAFE, "ChaCha20", "256-bit stream cipher, Grover-resistant"
    if re.search(r"\bdes\b", hay):
        return PqcStatus.REVIEW, "DES", "56-bit — broken; remediate"
    if any(t in hay for t in ("sha-512", "sha512", "sha-384", "sha384", "sha3-512", "sha3-384", "shake256")):
        return PqcStatus.SAFE, "SHA-2/3", "Grover-resistant digest (>=384-bit)"
    if any(t in hay for t in ("sha-256", "sha256", "sha3-256", "shake128", "sha-224", "sha224")):
        # SHA-256 is SAFE: Grover does not speed up collision search and NIST keeps SHA-2 approved.
        return PqcStatus.SAFE, "SHA-256", "Grover leaves ~128-bit; NIST keeps SHA-2 approved"
    return None


def _classify_identity(hay: str, tokens: set[str]) -> tuple[PqcStatus, str | None, str, bool]:
    """Return ``(status, family, reason, is_pqc_safe_family)`` from algorithm identity."""
    if any(s in hay for s in _PQC_SAFE_SUBSTRINGS):
        return PqcStatus.SAFE, "PQC", "Standardized post-quantum algorithm (FIPS 203/204/205)", True
    if any(s in hay for s in _PQC_REVIEW_SUBSTRINGS):
        return PqcStatus.REVIEW, "PQC-candidate", "Selected/stateful PQC, not a finalized FIPS standard — review", False
    if any(s in hay for s in _VULNERABLE_SUBSTRINGS) or (tokens & _VULNERABLE_TOKENS):
        return (
            PqcStatus.VULNERABLE,
            "classical-asymmetric",
            "Broken by Shor's algorithm (factoring / discrete log)",
            False,
        )
    sym = _classify_symmetric_or_hash(hay)
    if sym is not None:
        status, family, reason = sym
        return status, family, reason, False
    return PqcStatus.UNKNOWN, None, "Algorithm not recognized", False


def classify_crypto_asset(asset: CryptoAsset) -> PqcAssessment:
    """Classify one crypto asset's post-quantum status from its identity.

    Algorithm identity (name / algorithmFamily / curve) decides the verdict.
    ``nistQuantumSecurityLevel`` is used only as a corroborating signal: it
    promotes an otherwise-unrecognized asset to ``review`` (never ``safe``) and
    raises a data-quality flag when it conflicts with the identity verdict.
    """
    hay = _haystack(asset)
    tokens = _tokens(hay)
    status, family, reason, is_pqc_safe = _classify_identity(hay, tokens)

    level = asset.nist_quantum_security_level

    if status is PqcStatus.UNKNOWN and level is not None and level >= 1:
        return PqcAssessment(
            status=PqcStatus.REVIEW,
            family=family,
            reason="Declares a NIST PQC security category but the algorithm is unrecognized — review",
        )

    data_quality_flag = None
    if status is PqcStatus.VULNERABLE and level is not None and level >= 1:
        data_quality_flag = (
            f"Declares nistQuantumSecurityLevel {level} on a quantum-vulnerable algorithm — likely mislabeled"
        )
    elif status is PqcStatus.SAFE and is_pqc_safe and level == 0:
        data_quality_flag = "PQC algorithm declares nistQuantumSecurityLevel 0 — likely mislabeled"

    return PqcAssessment(status=status, family=family, reason=reason, data_quality_flag=data_quality_flag)


def assess_inventory(inventory: CryptoInventory) -> PqcSummary:
    """Classify every asset and roll up to an overall readiness verdict.

    Overall (conservative, most-severe-wins): any vulnerable -> ``at_risk``;
    else any review, or any *algorithm* asset we could not classify ->
    ``needs_review``; else any safe -> ``ready``; else ``not_assessed``.
    """
    results = tuple(PqcResult(asset, classify_crypto_asset(asset)) for asset in inventory.assets)
    counts = {status.value: 0 for status in PqcStatus}
    for result in results:
        counts[result.assessment.status.value] += 1

    unclassified_algorithms = sum(
        1 for r in results if r.assessment.status is PqcStatus.UNKNOWN and r.asset.asset_type == "algorithm"
    )

    if counts[PqcStatus.VULNERABLE.value]:
        overall = OVERALL_AT_RISK
    elif counts[PqcStatus.REVIEW.value] or unclassified_algorithms:
        overall = OVERALL_NEEDS_REVIEW
    elif counts[PqcStatus.SAFE.value]:
        overall = OVERALL_READY
    else:
        overall = OVERALL_NOT_ASSESSED

    return PqcSummary(overall=overall, counts=counts, results=results)
