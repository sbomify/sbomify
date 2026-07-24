"""NSA CNSA 2.0 compliance assessment plugin.

Grades each algorithm asset against the CNSA 2.0 allow-list for National
Security Systems: AES-256, SHA-384/512, ML-KEM-1024, ML-DSA-87, and the
SP 800-208 stateful hash-based signatures (LMS, XMSS). CNSA 1.0 holdovers
(RSA/DH at 3072+ bits, ECDSA/ECDH on NIST P-384) warn with the transition
deadline; everything else fails in an NSS context. This mirrors what
CBOMkit's quantum_safe.rego policy evaluates.

Composite names carry several facets (a cipher-suite name claims a cipher, a
key exchange, and a digest at once); every matched facet is graded and the
worst verdict wins.
"""

from __future__ import annotations

import re

from sbomify.apps.plugins.sdk import Finding
from sbomify.apps.sboms.crypto_inventory import CryptoAsset, CryptoInventory
from sbomify.apps.sboms.pqc import asset_identity_haystack, identity_tokens

from ._crypto_assessment import (
    NON_NIST_CIPHERS,
    STATEFUL_HASH_SIGS,
    TDEA_MARKERS,
    VERDICT_SEVERITY,
    CryptoInventoryPlugin,
    Verdict,
    curve_bits,
    key_bits,
    plain_dsa_present,
    strip_hash_names,
    worst,
)

_PLUGIN_NAME = "cnsa-2.0"
_DEADLINE = "2033"

_REMEDIATION_FAIL = (
    "Adopt a CNSA 2.0 algorithm: ML-KEM-1024 for key establishment, ML-DSA-87 for signatures, "
    "LMS/XMSS for firmware signing, AES-256 for encryption, SHA-384 or SHA-512 for hashing."
)
_REMEDIATION_TRANSITIONAL = (
    f"CNSA 1.0 algorithms are transitional: NSS must move to CNSA 2.0, exclusively by {_DEADLINE} "
    "(software and firmware signing earlier, per the NSA timeline)."
)

_TRANSITIONAL = "CNSA 1.0 transitional"

_SHA_DIGITS_RE = re.compile(r"sha3?[-_ ]?(\d{3})")
_LEGACY = ("md5", "md4", "md2", "rc4", "rc2", "arcfour", "skipjack")


def _classify_cnsa_facets(asset: CryptoAsset) -> list[Verdict]:
    hay = asset_identity_haystack(asset)
    tokens = identity_tokens(hay)
    # Digits attached to non-hash parts of the name; a SHA-256 suffix must not
    # satisfy an AES-256 or ML-KEM-1024 parameter check.
    digits = {int(n) for n in re.findall(r"\d{2,5}", strip_hash_names(hay))}
    sha_digits = {int(n) for n in _SHA_DIGITS_RE.findall(hay)}

    if any(s in hay for s in STATEFUL_HASH_SIGS):
        return [Verdict("pass", "CNSA 2.0", "SP 800-208 stateful hash-based signatures are CNSA 2.0 approved")]

    facets: list[Verdict] = []

    if "ml-kem" in hay or "mlkem" in hay or "kyber" in hay:
        if 1024 in digits:
            facets.append(Verdict("pass", "CNSA 2.0", "ML-KEM-1024 is the CNSA 2.0 key-establishment algorithm"))
        elif digits & {512, 768}:
            facets.append(Verdict("fail", "Non-compliant", "CNSA 2.0 requires the ML-KEM-1024 parameter set"))
        else:
            facets.append(
                Verdict("warning", "Parameter set unclear", "Declare the parameter set; CNSA 2.0 requires ML-KEM-1024")
            )

    if "ml-dsa" in hay or "mldsa" in hay or "dilithium" in hay:
        squashed = hay.replace(" ", "")
        if 87 in digits or "dilithium5" in squashed:
            facets.append(Verdict("pass", "CNSA 2.0", "ML-DSA-87 is the CNSA 2.0 signature algorithm"))
        elif digits & {44, 65} or "dilithium2" in squashed or "dilithium3" in squashed:
            facets.append(Verdict("fail", "Non-compliant", "CNSA 2.0 requires the ML-DSA-87 parameter set"))
        else:
            facets.append(
                Verdict("warning", "Parameter set unclear", "Declare the parameter set; CNSA 2.0 requires ML-DSA-87")
            )

    if "slh-dsa" in hay or "slhdsa" in hay or "sphincs" in hay:
        facets.append(Verdict("fail", "Non-compliant", "SLH-DSA is not in the CNSA 2.0 algorithm suite"))

    if "aes" in tokens:
        if 256 in digits:
            facets.append(Verdict("pass", "CNSA 2.0", "AES-256 is the CNSA 2.0 symmetric cipher"))
        elif digits & {128, 192}:
            facets.append(Verdict("fail", "Non-compliant", "CNSA 2.0 requires 256-bit AES keys"))
        else:
            facets.append(Verdict("warning", "Key size unclear", "Declare the key size; CNSA 2.0 requires AES-256"))

    if "sha" in hay:
        if sha_digits and sha_digits <= {384, 512}:
            facets.append(Verdict("pass", "CNSA 2.0", "SHA-384/SHA-512 are the CNSA 2.0 hash functions"))
        else:
            facets.append(Verdict("fail", "Non-compliant", "CNSA 2.0 permits only SHA-384 and SHA-512 for hashing"))

    if any(s in hay for s in ("ecdsa", "ecdh", "secp", "brainpool", "nistp")) or {"ec", "ecc"} & tokens:
        bits = curve_bits(asset, hay)
        if bits == 384 and "brainpool" not in hay:
            facets.append(
                Verdict(
                    "warning",
                    _TRANSITIONAL,
                    f"P-384 is CNSA 1.0; NSS must transition to CNSA 2.0 algorithms by {_DEADLINE}",
                )
            )
        else:
            facets.append(Verdict("fail", "Non-compliant", "CNSA permits only NIST P-384, and only transitionally"))

    if any(s in hay for s in ("ed25519", "ed448", "x25519", "x448", "curve25519", "curve448")):
        facets.append(Verdict("fail", "Non-compliant", "Edwards/Montgomery curves are not in the CNSA suite"))

    if "rsa" in hay or {"dh", "dhe", "ffdh"} & tokens or "diffie" in hay:
        bits = key_bits(hay)
        if bits is not None and bits >= 3072:
            facets.append(
                Verdict(
                    "warning",
                    _TRANSITIONAL,
                    f"{bits}-bit keys are CNSA 1.0; NSS must transition to CNSA 2.0 algorithms by {_DEADLINE}",
                )
            )
        else:
            facets.append(
                Verdict("fail", "Non-compliant", "CNSA 1.0 requires at least 3072-bit keys, and only transitionally")
            )

    if plain_dsa_present(hay):
        facets.append(Verdict("fail", "Non-compliant", "DSA is not in the CNSA suite"))

    if (
        any(s in hay for s in _LEGACY)
        or any(s in hay for s in NON_NIST_CIPHERS)
        or any(s in hay for s in TDEA_MARKERS)
        or "des" in tokens
    ):
        facets.append(Verdict("fail", "Non-compliant", "Algorithm is not in the CNSA suite"))

    return facets


def classify_cnsa(asset: CryptoAsset) -> Verdict:
    verdict = worst(_classify_cnsa_facets(asset))
    if verdict is not None:
        return verdict
    return Verdict("info", "Not recognized", "Algorithm not recognized; verify against the CNSA 2.0 suite manually")


class Cnsa2Plugin(CryptoInventoryPlugin):
    """Grade crypto assets against the NSA CNSA 2.0 algorithm suite."""

    PLUGIN_NAME = _PLUGIN_NAME
    VERSION = "1.0.0"
    STANDARD_NAME = "NSA CNSA 2.0"
    STANDARD_VERSION = "September 2022 advisory"
    STANDARD_URL = "https://media.defense.gov/2022/Sep/07/2003071834/-1/-1/0/CSA_CNSA_2.0_ALGORITHMS_.PDF"
    ERROR_TITLE = "CNSA 2.0 assessment error"

    def build_findings(self, inventory: CryptoInventory, sbom_id: str) -> list[Finding]:
        return [self._finding(index, asset) for index, asset in enumerate(inventory.assets)]

    def _finding(self, index: int, asset: CryptoAsset) -> Finding:
        name = asset.name or "Unnamed asset"
        finding_id = f"{_PLUGIN_NAME}:{asset.bom_ref or asset.name or f'asset-{index}'}"

        verdict = classify_cnsa(asset)
        if verdict.label == "Not recognized" and asset.asset_type is not None and asset.asset_type != "algorithm":
            return self.not_assessed_finding(finding_id, name, asset, "against CNSA 2.0", "cnsa_status")

        remediation = None
        if verdict.status == "fail":
            remediation = _REMEDIATION_FAIL
        elif verdict.label == _TRANSITIONAL:
            remediation = _REMEDIATION_TRANSITIONAL
        return Finding(
            id=finding_id,
            title=f"{name}: {verdict.label}",
            description=verdict.reason,
            status=verdict.status,
            severity=VERDICT_SEVERITY[verdict.status],
            remediation=remediation,
            metadata={
                "cnsa_status": verdict.label.lower().replace(" ", "_").replace(".", "_"),
                "asset_type": asset.asset_type,
                "asset_name": asset.name,
            },
        )
