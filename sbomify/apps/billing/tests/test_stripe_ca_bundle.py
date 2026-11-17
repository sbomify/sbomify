"""Which certificates the Stripe connection trusts.

stripe-python ships its own CA file and verifies against it by default. That
copy still holds roots that issued the compromised eMudhra intermediates
(GHSA-6q48-6c7w-9gw2), so a certificate from one of them would pass for
api.stripe.com. The client is pointed at certifi instead, the store every other
HTTPS call in sbomify uses.
"""

from __future__ import annotations

import hashlib
import ssl
from pathlib import Path

import certifi
import stripe

# SHA-256 of the DER encoding of each root that issued one of the compromised intermediates.
ISSUERS_OF_COMPROMISED_INTERMEDIATES = {
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4": "AAA Certificate Services",
    "7dd78d5f4f13459a83dff9abbba62edbaf6f2d102bf257fd712f4d9f2746ed8d": "emSign Root TLS CA - G3",
    "f2edaaff3d9b701fb4d14c9f285f8c0bad90fc3bcc1fa07d47f4718edaba34a5": "emSign Root CS CA - G3",
}


def _fingerprints(bundle: str | Path) -> set[str]:
    begin, end = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
    return {
        hashlib.sha256(ssl.PEM_cert_to_DER_cert(f"{begin}{block.split(end)[0]}{end}\n")).hexdigest()
        for block in Path(bundle).read_text().split(begin)[1:]
    }


def _trusted_issuers(bundle: str | Path) -> list[str]:
    fingerprints = _fingerprints(bundle)
    return sorted(name for fp, name in ISSUERS_OF_COMPROMISED_INTERMEDIATES.items() if fp in fingerprints)


def test_stripe_verifies_against_certifi() -> None:
    assert stripe.ca_bundle_path == certifi.where()


def test_the_bundle_stripe_uses_trusts_no_issuer_of_a_compromised_intermediate() -> None:
    assert _fingerprints(stripe.ca_bundle_path), "the bundle should hold certificates"
    assert _trusted_issuers(stripe.ca_bundle_path) == []


def test_the_bundle_stripe_ships_is_the_reason_for_the_override() -> None:
    """Once a stripe release drops these roots this fails, and the override can be reconsidered."""
    shipped = Path(stripe.__file__).parent / "data" / "ca-certificates.crt"
    assert _trusted_issuers(shipped)
