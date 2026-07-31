"""BSI TR-02102 crypto-mechanisms assessment plugin.

Grades algorithm and protocol assets against BSI TR-02102 (Cryptographic
Mechanisms: Recommendations and Key Lengths): 3000-bit floor for RSA/DH/DSA,
250-bit floor for elliptic curves, mode checks for block ciphers, and the
TR-02102-2 TLS version ladder. Complements the bsi-tr03183 plugin, which
checks the SBOM document itself rather than the cryptography it declares.

Composite names carry several facets; every matched facet is graded and the
worst verdict wins, so a sub-floor key never hides behind an approved digest.

Notable divergences from the NIST checks: RSA-2048 fails outright (BSI's
floor is 3000 bits), SHA-224 fails (below BSI's security floor), and
FrodoKEM and Classic McEliece pass (BSI recommends both; NIST standardized
neither).
"""

from __future__ import annotations

from sbomify.apps.plugins.sdk import Finding
from sbomify.apps.sboms.crypto_inventory import CryptoAsset, CryptoInventory
from sbomify.apps.sboms.pqc import asset_identity_haystack, identity_tokens

from ._crypto_assessment import (
    APPROVED_HASH_RE,
    EC_MARKERS,
    EDWARDS_CURVES,
    NON_NIST_CIPHERS,
    SHA224_RE,
    STATEFUL_HASH_SIGS,
    TDEA_MARKERS,
    VERDICT_SEVERITY,
    CryptoInventoryPlugin,
    Verdict,
    curve_bits,
    key_bits,
    plain_dsa_present,
    sha1_present,
    worst,
)

_PLUGIN_NAME = "bsi-tr02102"

_REMEDIATION_FAIL = (
    "Move to a TR-02102-1 recommended mechanism: AES (GCM/CCM), SHA-2/SHA-3, RSA or DH at "
    "3000+ bits, elliptic curves at 250+ bits, or a recommended PQC scheme (ML-KEM, FrodoKEM, "
    "Classic McEliece)."
)

# BSI recommends the NIST-standardized lattice schemes plus FrodoKEM and
# Classic McEliece, and the SP 800-208 stateful hash-based signatures.
_RECOMMENDED_PQC = ("ml-kem", "mlkem", "kyber", "ml-dsa", "mldsa", "dilithium", "frodo", "mceliece")

# TR-02102-2 grades TLS by exact version, not a numeric ladder: anything that
# is not a known TLS version (SSLv3 shows up as type=tls version=3.0) fails.
_TLS_VERSIONS = {"1.0": "fail", "1.1": "fail", "1.2": "warning", "1.3": "pass"}


def _classify_tls(version: str | None) -> Verdict:
    if not version:
        return Verdict("info", "Version not declared", "TLS version not declared; cannot grade against TR-02102-2")
    normalized = version.strip().lower().removeprefix("tlsv").removeprefix("tls").strip()
    grade = _TLS_VERSIONS.get(normalized)
    if grade == "pass":
        return Verdict("pass", "Recommended", f"TLS {normalized} is recommended by TR-02102-2")
    if grade == "warning":
        return Verdict(
            "warning",
            "Conditional",
            "TLS 1.2 is only recommended with the TR-02102-2 condition list (approved suites, PFS); prefer TLS 1.3",
        )
    if grade == "fail":
        return Verdict("fail", "Not recommended", f"TLS {normalized} is not recommended by TR-02102-2; use TLS 1.3")
    return Verdict(
        "fail", "Not recommended", f"'{version}' is not a recommended TLS protocol version (TR-02102-2); use TLS 1.3"
    )


def classify_bsi(asset: CryptoAsset) -> Verdict:
    if asset.asset_type == "protocol":
        protocol = asset.protocol or {}
        proto_type = str(protocol.get("type") or "").lower()
        if proto_type == "tls" or "tls" in (asset.name or "").lower():
            return _classify_tls(str(protocol.get("version")) if protocol.get("version") is not None else None)
        return Verdict("info", "Not assessed", "Non-TLS protocols are not assessed against TR-02102-2 by this check")

    hay = asset_identity_haystack(asset)
    tokens = identity_tokens(hay)
    mode = (asset.mode or "").lower()

    if any(s in hay for s in _RECOMMENDED_PQC) or any(s in hay for s in STATEFUL_HASH_SIGS):
        return Verdict("pass", "Recommended", "TR-02102-1 recommended post-quantum or hash-based mechanism")

    facets: list[Verdict] = []

    if any(s in hay for s in ("md5", "md4", "md2")):
        facets.append(Verdict("fail", "Not recommended", "MD-family hashes fall far below the TR-02102-1 floor"))
    if any(t in tokens for t in ("rc4", "rc2", "arcfour")) or "skipjack" in hay:
        facets.append(Verdict("fail", "Not recommended", "Legacy cipher outside TR-02102-1 recommendations"))
    if any(s in hay for s in TDEA_MARKERS) or "des" in tokens:
        facets.append(Verdict("fail", "Not recommended", "DES/TDEA are not recommended by TR-02102-1"))

    if "hmac" in hay:
        if sha1_present(hay):
            facets.append(
                Verdict("warning", "Below recommendation", "HMAC-SHA-1 falls below the TR-02102-1 hash floor")
            )
        else:
            facets.append(Verdict("pass", "Recommended", "HMAC with a SHA-2/SHA-3 hash is recommended"))
    elif sha1_present(hay) or SHA224_RE.search(hay):
        facets.append(Verdict("fail", "Not recommended", "Hashes below 240-bit output fall under the TR-02102-1 floor"))
    elif APPROVED_HASH_RE.search(hay):
        facets.append(Verdict("pass", "Recommended", "SHA-2/SHA-3 at 256+ bits is recommended"))

    if "aes" in tokens:
        if mode == "ecb" or "ecb" in tokens:
            facets.append(Verdict("fail", "Not recommended", "ECB mode leaks plaintext structure; use GCM or CCM"))
        elif mode == "cbc" or "cbc" in tokens:
            facets.append(Verdict("warning", "Conditional", "Plain CBC is padding-oracle prone; prefer GCM or CCM"))
        else:
            facets.append(Verdict("pass", "Recommended", "AES is recommended at 128-bit keys and above"))
    elif any(s in hay for s in NON_NIST_CIPHERS):
        facets.append(Verdict("info", "Out of scope", "Not in the TR-02102-1 recommended-mechanisms list"))

    if any(s in hay for s in EDWARDS_CURVES):
        facets.append(
            Verdict("pass", "Recommended", "Edwards/Montgomery curve at or above the TR-02102-1 250-bit floor")
        )
    elif any(s in hay for s in EC_MARKERS) or {"ec", "ecc"} & tokens:
        bits = curve_bits(asset, hay)
        if bits is None:
            facets.append(
                Verdict("info", "Size not declared", "Curve size not declared; cannot verify the 250-bit floor")
            )
        elif bits < 250:
            facets.append(
                Verdict("fail", "Not recommended", f"{bits}-bit curves fall below the TR-02102-1 250-bit floor")
            )
        else:
            facets.append(Verdict("pass", "Recommended", f"{bits}-bit curve meets the TR-02102-1 250-bit floor"))

    if plain_dsa_present(hay) or "rsa" in hay or {"dh", "dhe", "ffdh"} & tokens or "diffie" in hay:
        bits = key_bits(hay)
        if bits is None:
            facets.append(
                Verdict("info", "Size not declared", "Key size not declared; cannot verify the 3000-bit floor")
            )
        elif bits < 3000:
            facets.append(
                Verdict("fail", "Not recommended", f"{bits}-bit keys fall below the TR-02102-1 3000-bit floor")
            )
        else:
            facets.append(Verdict("pass", "Recommended", f"{bits}-bit key meets the TR-02102-1 3000-bit floor"))

    verdict = worst(facets)
    if verdict is not None:
        return verdict
    return Verdict("info", "Not recognized", "Mechanism not recognized; verify against TR-02102-1 manually")


class BsiTr02102Plugin(CryptoInventoryPlugin):
    """Grade crypto mechanisms against BSI TR-02102 recommendations."""

    PLUGIN_NAME = _PLUGIN_NAME
    VERSION = "1.0.0"
    STANDARD_NAME = "BSI TR-02102 Cryptographic Mechanisms"
    STANDARD_VERSION = "TR-02102-1/-2 (2026-01)"
    STANDARD_URL = (
        "https://www.bsi.bund.de/EN/Themen/Unternehmen-und-Organisationen/Standards-und-Zertifizierung/"
        "Technische-Richtlinien/TR-nach-Thema-sortiert/tr02102/tr02102_node.html"
    )
    ERROR_TITLE = "BSI TR-02102 assessment error"

    def build_findings(self, inventory: CryptoInventory, sbom_id: str) -> list[Finding]:
        return [self._finding(index, asset) for index, asset in enumerate(inventory.assets)]

    def _finding(self, index: int, asset: CryptoAsset) -> Finding:
        name = asset.name or "Unnamed asset"
        finding_id = f"{_PLUGIN_NAME}:{asset.bom_ref or asset.name or f'asset-{index}'}"
        verdict = classify_bsi(asset)

        if (
            verdict.label == "Not recognized"
            and asset.asset_type is not None
            and asset.asset_type not in ("algorithm", "protocol")
        ):
            return self.not_assessed_finding(finding_id, name, asset, "against TR-02102", "bsi_status")

        return Finding(
            id=finding_id,
            title=f"{name}: {verdict.label}",
            description=verdict.reason,
            status=verdict.status,
            severity=VERDICT_SEVERITY[verdict.status],
            remediation=_REMEDIATION_FAIL if verdict.status == "fail" else None,
            metadata={
                "bsi_status": verdict.label.lower().replace(" ", "_"),
                "asset_type": asset.asset_type,
                "asset_name": asset.name,
            },
        )
