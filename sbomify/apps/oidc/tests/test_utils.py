"""Unit tests for ``sbomify.apps.oidc.utils.verify_github_oidc_token``."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sbomify.apps.oidc.utils import (
    OIDCExpiredToken,
    OIDCInvalidAudience,
    OIDCInvalidIssuer,
    OIDCInvalidSignature,
    OIDCJWKSUnavailable,
    verify_github_oidc_token,
)


class TestHappyPath:
    def test_valid_token_returns_claims(self, github_claims_factory, mock_github_jwks) -> None:
        token = github_claims_factory()
        claims = verify_github_oidc_token(token)
        assert claims["repository"] == "acme/widget"
        assert claims["actor"] == "octocat"
        assert claims["aud"] == "sbomify.com"


class TestSignatureFailures:
    def test_token_signed_with_unknown_key_fails(self, mock_github_jwks) -> None:
        """A JWT signed by an attacker's key must fail signature verification."""
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        attacker_pem = attacker_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        forged = pyjwt.encode(
            {"iss": "x", "aud": "x", "exp": time.time() + 60, "iat": time.time(), "sub": "x"},
            attacker_pem,
            algorithm="RS256",
            headers={"kid": "test-kid-1"},  # claims a known kid
        )
        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(forged)

    def test_token_with_unknown_kid_fails(self, github_claims_factory, mock_github_jwks, rsa_keypair) -> None:
        """A JWT with a kid not in the JWKS must fail (even after JWKS refresh)."""
        token = pyjwt.encode(
            {
                "iss": "https://token.actions.githubusercontent.com",
                "aud": "sbomify.com",
                "exp": time.time() + 60,
                "iat": time.time(),
                "sub": "x",
            },
            rsa_keypair["private_pem"],
            algorithm="RS256",
            headers={"kid": "totally-unknown-kid"},
        )
        with pytest.raises(OIDCInvalidSignature, match="no JWK matches"):
            verify_github_oidc_token(token)

    def test_token_missing_kid_header_fails(self, rsa_keypair, mock_github_jwks) -> None:
        token = pyjwt.encode(
            {"iss": "x", "aud": "x", "exp": time.time() + 60, "iat": time.time(), "sub": "x"},
            rsa_keypair["private_pem"],
            algorithm="RS256",
            # NO kid header
        )
        with pytest.raises(OIDCInvalidSignature, match="missing 'kid'"):
            verify_github_oidc_token(token)


class TestClaimFailures:
    def test_wrong_issuer_fails(self, github_claims_factory, mock_github_jwks) -> None:
        token = github_claims_factory(iss="https://evil.example.com")
        with pytest.raises(OIDCInvalidIssuer):
            verify_github_oidc_token(token)

    def test_wrong_audience_fails(self, github_claims_factory, mock_github_jwks) -> None:
        token = github_claims_factory(aud="some-other-service.com")
        with pytest.raises(OIDCInvalidAudience):
            verify_github_oidc_token(token)

    def test_expired_token_fails(self, github_claims_factory, mock_github_jwks) -> None:
        token = github_claims_factory(exp=int(time.time()) - 60, iat=int(time.time()) - 120)
        with pytest.raises(OIDCExpiredToken):
            verify_github_oidc_token(token)

    def test_missing_required_claim_fails(self, github_claims_factory, mock_github_jwks) -> None:
        """The ``require`` option enforces presence of iss/aud/exp/iat/sub."""
        token = github_claims_factory(sub=None)
        # PyJWT raises MissingRequiredClaimError → mapped to OIDCInvalidSignature
        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(token)


class TestJWKSFailures:
    def test_jwks_http_error_raises_unavailable(self, mocker) -> None:
        from django.core.cache import cache

        cache.delete("oidc:github:jwks")
        mocker.patch(
            "sbomify.apps.oidc.utils.requests.get",
            side_effect=requests.exceptions.ConnectionError("boom"),
        )
        with pytest.raises(OIDCJWKSUnavailable):
            verify_github_oidc_token("dummy.token.here")

    def test_jwks_is_cached_across_calls(self, github_claims_factory, mock_github_jwks) -> None:
        token1 = github_claims_factory()
        token2 = github_claims_factory()
        verify_github_oidc_token(token1)
        verify_github_oidc_token(token2)
        # JWKS fetch should have happened exactly once thanks to the cache
        assert mock_github_jwks.call_count == 1

    def test_jwks_refreshed_on_kid_miss(self, github_claims_factory, mocker, rsa_keypair) -> None:
        """If the cached JWKS doesn't contain the token's kid, we refresh once."""
        from django.core.cache import cache

        cache.delete("oidc:github:jwks")

        # First fetch: empty JWKS (cache will store this). Second fetch (after
        # kid-miss invalidation): the real JWK. PyJWKClient should succeed
        # on the second pass.
        empty_response = MagicMock()
        empty_response.json.return_value = {"keys": []}
        empty_response.raise_for_status.return_value = None

        real_response = MagicMock()
        real_response.json.return_value = {"keys": [rsa_keypair["jwk"]]}
        real_response.raise_for_status.return_value = None

        mocker.patch(
            "sbomify.apps.oidc.utils.requests.get",
            side_effect=[empty_response, real_response],
        )

        token = github_claims_factory()
        claims = verify_github_oidc_token(token)
        assert claims["repository"] == "acme/widget"


class TestDoesNotLeakInternals:
    def test_signature_mismatch_does_not_reveal_which_check_failed(
        self, github_claims_factory, mock_github_jwks
    ) -> None:
        """Repository/sub/etc. checks happen later; an early signature failure
        must surface as ``OIDCInvalidSignature`` so callers can't probe.
        """
        # A token with the wrong audience BUT also a bad signature should
        # be caught by signature first — but PyJWT verifies signature first
        # by default, so this confirms ordering.
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        attacker_pem = attacker_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        forged = pyjwt.encode(
            {
                "iss": "https://token.actions.githubusercontent.com",
                "aud": "wrong-audience",  # also wrong
                "exp": time.time() + 60,
                "iat": time.time(),
                "sub": "x",
            },
            attacker_pem,
            algorithm="RS256",
            headers={"kid": "test-kid-1"},
        )
        # Should raise OIDCInvalidSignature, NOT OIDCInvalidAudience —
        # the audience error would tell the attacker their forged
        # signature was accepted.
        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(forged)
