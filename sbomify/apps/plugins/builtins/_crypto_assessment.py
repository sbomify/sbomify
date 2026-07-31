"""Shared scaffolding for crypto-inventory assessment plugins.

The crypto policy plugins (SP 800-131A, BSI TR-02102, certificate lifecycle,
CNSA 2.0) all follow the same shape: parse the immutable artifact, derive the
crypto inventory, emit one finding per asset the check applies to. This base
centralizes that shape plus the identity tables the classifiers share, so a
new algorithm spelling lands in one place instead of drifting per plugin.

Composite names ("RSA-1024-SHA256", "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA")
carry several algorithm facets at once. Classifiers collect a verdict per
matched facet and return the worst one via :func:`worst`, so a weak member
can never hide behind an approved one.

Empty inventories skip quietly here — pqc-readiness alone owns the visible
"CBOM with no crypto assets" misfire warning, so an empty CBOM does not stack
one warning per enabled crypto plugin.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sbomify.apps.plugins.sdk import (
    AssessmentCategory,
    AssessmentPlugin,
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
    ScanMode,
)
from sbomify.apps.plugins.sdk.base import SBOMContext
from sbomify.apps.sboms.crypto_inventory import CryptoAsset, CryptoInventory, derive_crypto_inventory


@dataclass(frozen=True)
class Verdict:
    status: str  # fail | warning | pass | info
    label: str
    reason: str
    sunset: str | None = None


# Finding.status keys off the verdict; severity is cosmetic.
VERDICT_SEVERITY = {"fail": "high", "warning": "medium", "pass": "info", "info": "info"}  # nosec B105 - labels

_STATUS_RANK = {"fail": 0, "warning": 1, "pass": 2, "info": 3}  # nosec B105 - verdict ordering


def worst(verdicts: list[Verdict]) -> Verdict | None:
    """The most severe verdict of the matched facets (fail < warning < pass < info)."""
    if not verdicts:
        return None
    return min(verdicts, key=lambda v: _STATUS_RANK.get(v.status, 4))


# Identity tables shared by the classifiers. A new spelling belongs here, once.
PQC_STANDARDIZED = ("ml-kem", "mlkem", "kyber", "ml-dsa", "mldsa", "dilithium", "slh-dsa", "slhdsa", "sphincs")
STATEFUL_HASH_SIGS = ("xmss", "lms", "hss")
PQC_NOT_FINAL = ("fn-dsa", "falcon", "hqc", "bike", "mceliece", "frodo", "ntru", "saber")
TDEA_MARKERS = ("3des", "tdea", "des-ede", "desede", "des3", "triple des", "tripledes", "triple-des")
EDWARDS_CURVES = ("ed25519", "ed448", "x25519", "x448", "curve25519", "curve448")
EC_MARKERS = ("ecdsa", "ecdh", "secp", "sect", "brainpool", "prime256v1", "nistp", "ecmqv", "ecies")
NON_NIST_CIPHERS = ("chacha", "poly1305", "salsa20")

SHA1_RE = re.compile(r"sha[-_ ]?1(?![0-9])")
# TLS/OpenSSL suite naming spells HMAC-SHA-1 as a bare trailing "SHA"
# (TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA); "sha" not followed by a digit or
# letter is SHA-1 in that vocabulary.
SHA1_BARE_RE = re.compile(r"(?:^|[^a-z0-9])sha(?![a-z0-9])(?![-_ ]?\d)")
SHA224_RE = re.compile(r"sha3?[-_ ]?224|512[/_-]224")
# SHA-256/384/512 and SHA-3, including the approved truncated SHA-512/256;
# SHA-512/224 is caught by SHA224_RE before this is consulted.
APPROVED_HASH_RE = re.compile(r"sha3?[-_ ]?(256|384|512)(?![0-9])|shake")


def sha1_present(hay: str) -> bool:
    return bool(SHA1_RE.search(hay) or SHA1_BARE_RE.search(hay))


# "dsa" as a substring, but not the tail of ECDSA/EdDSA; PQC family names
# (ML-DSA, SLH-DSA, FN-DSA) are stripped before matching.
_PLAIN_DSA_RE = re.compile(r"(?<!ec)(?<!ed)dsa")
_PQC_DSA_RE = re.compile(r"(?:ml|slh|fn)[-_ ]?dsa")


def plain_dsa_present(hay: str) -> bool:
    """True when the identity names classic DSA (JCA composites included)."""
    return bool(_PLAIN_DSA_RE.search(_PQC_DSA_RE.sub(" ", hay)))


def strip_hash_names(hay: str) -> str:
    """Remove sha-N tokens so a digest suffix is not read as a key size."""
    return re.sub(r"sha3?[-_ ]?\d+(?:[/_-]\d+)?", " ", hay)


# Real-world RSA/DH/DSA modulus sizes. Free-text names carry incidental
# numbers (years, RFC numbers); only these count as a declared key size.
STANDARD_MODULI = frozenset({512, 768, 1024, 1536, 2048, 3072, 4096, 6144, 7680, 8192, 15360, 16384})


def key_bits(hay: str) -> int | None:
    """Largest declared modulus size in an identity haystack, or None."""
    sizes = [int(n) for n in re.findall(r"\d{3,5}", strip_hash_names(hay))]
    plausible = [n for n in sizes if n in STANDARD_MODULI]
    return max(plausible) if plausible else None


_KNOWN_CURVE_BITS = {160, 163, 192, 224, 233, 239, 256, 283, 320, 384, 409, 512, 521, 571}


def curve_bits(asset: CryptoAsset, hay: str) -> int | None:
    """Curve size from the asset's curve fields, falling back to its name."""
    for field in (asset.normalized_curve, asset.curve, asset.parameter_set, strip_hash_names(hay)):
        if not field:
            continue
        sizes = [int(n) for n in re.findall(r"\d{3}", field.lower()) if int(n) in _KNOWN_CURVE_BITS]
        if sizes:
            return sizes[0]
    return None


def summarize(findings: list[Finding]) -> AssessmentSummary:
    return AssessmentSummary(
        total_findings=len(findings),
        pass_count=sum(1 for f in findings if f.status == "pass"),
        fail_count=sum(1 for f in findings if f.status == "fail"),
        warning_count=sum(1 for f in findings if f.status == "warning"),
        error_count=sum(1 for f in findings if f.status == "error"),
        info_count=sum(1 for f in findings if f.status == "info"),
    )


class CryptoInventoryPlugin(AssessmentPlugin):
    """Template for plugins that grade the derived crypto inventory."""

    PLUGIN_NAME: str = ""
    VERSION: str = "1.0.0"
    STANDARD_NAME: str = ""
    STANDARD_VERSION: str = ""
    STANDARD_URL: str = ""
    ERROR_TITLE: str = "Assessment error"
    EMPTY_DESCRIPTION: str = "This document declares no crypto-asset components; nothing to assess."

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=self.PLUGIN_NAME,
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
            scan_mode=ScanMode.ONE_SHOT,
            supported_bom_types=["cbom", "sbom"],
            requires_crypto_assets=True,
        )

    def build_findings(self, inventory: CryptoInventory, sbom_id: str) -> list[Finding]:
        raise NotImplementedError

    def not_assessed_finding(
        self, finding_id: str, name: str, asset: CryptoAsset, check_name: str, status_key: str
    ) -> Finding:
        """Info finding for a non-algorithm asset this check does not grade."""
        kind = (asset.asset_type or "asset").replace("-", " ")
        return Finding(
            id=finding_id,
            title=f"{name}: {kind} (not assessed)",
            description=f"{kind.capitalize()} assets are not assessed {check_name} by this check.",
            status="info",
            severity="info",
            metadata={status_key: "not_assessed", "asset_type": asset.asset_type, "asset_name": asset.name},
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict[str, Any] | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        try:
            document = json.loads(sbom_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            return self._error_result(f"Invalid JSON: {exc}")
        except OSError as exc:  # pragma: no cover - defensive
            return self._error_result(f"Failed to read SBOM: {exc}")

        if not isinstance(document, dict):
            return self._error_result("SBOM is not a JSON object")

        findings = self.build_findings(derive_crypto_inventory(document), sbom_id)
        metadata: dict[str, Any] = {
            "standard_name": self.STANDARD_NAME,
            "standard_version": self.STANDARD_VERSION,
            "standard_url": self.STANDARD_URL,
        }
        if not findings:
            metadata["skipped"] = True
            findings = [
                Finding(
                    id=f"{self.PLUGIN_NAME}:no-assets",
                    title="Nothing to assess",
                    description=self.EMPTY_DESCRIPTION,
                    status="info",
                    severity="info",
                )
            ]

        return AssessmentResult(
            plugin_name=self.PLUGIN_NAME,
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summarize(findings),
            findings=findings,
            metadata=metadata,
        )

    def _error_result(self, message: str) -> AssessmentResult:
        return AssessmentResult(
            plugin_name=self.PLUGIN_NAME,
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(total_findings=1, error_count=1),
            findings=[
                Finding(
                    id=f"{self.PLUGIN_NAME}:error",
                    title=self.ERROR_TITLE,
                    description=message,
                    status="error",
                    severity="high",
                )
            ],
            metadata={"error": True},
        )
