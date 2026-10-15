"""sbomify's CRA export key: signs each bundle and publishes its public half.

The signature is ECDSA P-256 over the ZIP's SHA-256, DER encoded and written
base64, which is what ``cosign sign-blob --key`` emits, so
``cosign verify-blob --key <public key> --signature <file>.sig`` and
``openssl dgst -sha256 -verify`` both check it without sbomify shelling out.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import logging
import re

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings

logger = logging.getLogger(__name__)

ALGORITHM = "ecdsa-p256-sha256"
ENCODING = "base64-der"

_PUBLIC_PEM = re.compile(r"-----BEGIN PUBLIC KEY-----.*?-----END PUBLIC KEY-----", re.S)


def _pem_bytes(value: str) -> bytes:
    # An env file holds one line per variable, so a PEM can arrive with escaped newlines.
    return value.replace("\\n", "\n").strip().encode()


def key_id(public_key: ec.EllipticCurvePublicKey) -> str:
    """The first 16 hex characters of SHA-256 over the key's SPKI DER."""
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()[:16]


@functools.cache
def _load(value: str) -> tuple[ec.EllipticCurvePrivateKey | None, str]:
    """Parse the configured key once per value: ``(key, "")``, or ``(None, problem)``.

    The problem names the reason and never the value, and is logged here, so a
    misconfigured key warns once rather than on every export.
    """
    try:
        key = serialization.load_pem_private_key(_pem_bytes(value), password=None)
    except TypeError:
        problem = "it is encrypted; store it unencrypted"
    except (ValueError, UnsupportedAlgorithm):
        problem = "it is not a PEM private key"
    else:
        if isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1):
            return key, ""
        problem = "it is not an EC P-256 key"
    logger.warning("CRA_EXPORT_SIGNING_KEY is set but %s, so CRA exports stay unsigned", problem)
    return None, problem


def key_problem() -> str:
    """Why the configured key cannot sign, or "" when it is unset or usable."""
    value = settings.CRA_EXPORT_SIGNING_KEY
    return _load(value)[1] if value else ""


def signing_key() -> tuple[ec.EllipticCurvePrivateKey, str] | None:
    """The export key and its id, or None when it is unset or unusable."""
    value = settings.CRA_EXPORT_SIGNING_KEY
    if not value:
        return None
    key, _ = _load(value)
    if key is None:
        return None
    return key, key_id(key.public_key())


def sign(data: bytes, key: ec.EllipticCurvePrivateKey) -> bytes:
    return base64.b64encode(key.sign(data, ec.ECDSA(hashes.SHA256())))


def public_key_pem(kid: str) -> bytes | None:
    """The PEM of the current or a retired export key with this id, or None."""
    candidates: list[ec.EllipticCurvePublicKey] = []
    current = signing_key()
    if current is not None:
        candidates.append(current[0].public_key())
    for block in _PUBLIC_PEM.findall(_pem_bytes(settings.CRA_EXPORT_SIGNING_RETIRED_PUBLIC_KEYS).decode()):
        try:
            retired = serialization.load_pem_public_key(block.encode())
        except (ValueError, UnsupportedAlgorithm):
            logger.warning("Skipping an unreadable key in CRA_EXPORT_SIGNING_RETIRED_PUBLIC_KEYS")
            continue
        if isinstance(retired, ec.EllipticCurvePublicKey):
            candidates.append(retired)
    for public_key in candidates:
        if key_id(public_key) == kid:
            return public_key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return None
