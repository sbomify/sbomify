"""Shared fixtures for OIDC tests.

The big one is ``fake_github_oidc`` — a fixture that mints a realistic
RS256-signed GitHub-shaped OIDC JWT and mocks the JWKS endpoint to
return the matching public key. Tests can override any claim (issuer,
audience, exp, repository, sub, …) and the per-test JWT will be signed
correctly so the only thing under test is the claim-validation logic
inside ``verify_github_oidc_token``.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings


@pytest.fixture
def rsa_keypair() -> dict[str, Any]:
    """Generate a fresh RSA keypair for the test session.

    Returns the private key (PEM) for signing JWTs and the JWKS-shape
    dict for the public key so tests can drop it into the JWKS cache or
    return it from a mocked ``requests.get``.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    import base64

    def _b64(i: int) -> str:
        b = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "test-kid-1",
        "alg": "RS256",
        "use": "sig",
        "n": _b64(public_numbers.n),
        "e": _b64(public_numbers.e),
    }
    return {
        "private_pem": private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        "jwk": jwk,
    }


@pytest.fixture
def github_claims_factory(rsa_keypair: dict[str, Any]):
    """Return a callable that builds a signed JWT with overridable claims."""

    def _build(**overrides: Any) -> str:
        now = int(time.time())
        defaults = {
            "iss": settings.OIDC_GITHUB_ISSUER,
            "aud": settings.OIDC_GITHUB_AUDIENCE,
            "iat": now,
            "exp": now + 300,
            "sub": "repo:acme/widget:ref:refs/heads/main",
            "repository": "acme/widget",
            "repository_owner": "acme",
            "ref": "refs/heads/main",
            "workflow_ref": "acme/widget/.github/workflows/publish.yml@refs/heads/main",
            "actor": "octocat",
            "run_id": "12345",
        }
        defaults.update(overrides)
        return jwt.encode(
            defaults,
            rsa_keypair["private_pem"],
            algorithm="RS256",
            headers={"kid": rsa_keypair["jwk"]["kid"]},
        )

    return _build


@pytest.fixture
def mock_github_jwks(mocker, rsa_keypair: dict[str, Any]) -> Any:
    """Patch the JWKS HTTP fetch + clear the Django cache.

    Returns the mock so tests can override what JWKS is returned (e.g.
    to simulate a kid mismatch or a fetch failure).
    """
    from django.core.cache import cache

    cache.delete("oidc:github:jwks")
    mock_response = MagicMock()
    mock_response.json.return_value = {"keys": [rsa_keypair["jwk"]]}
    mock_response.raise_for_status.return_value = None
    return mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=mock_response)
