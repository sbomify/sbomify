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

        cache.delete("sbomify:trusted:oidc:github:jwks")
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

        cache.delete("sbomify:trusted:oidc:github:jwks")
        cache.delete("sbomify:trusted:oidc:github:jwks:last_refresh")

        # First fetch returns a JWKS with a DIFFERENT kid than the token's
        # — passes structural validation (real RSA key, ≥2048 bits) so it
        # gets cached, but the token's kid doesn't match. The kid-miss
        # branch then triggers ONE forced refresh, which returns the
        # real JWK with the matching kid.
        other_jwk = dict(rsa_keypair["jwk"])
        other_jwk["kid"] = "some-other-kid"
        stale_response = MagicMock()
        stale_response.json.return_value = {"keys": [other_jwk]}
        stale_response.raise_for_status.return_value = None

        real_response = MagicMock()
        real_response.json.return_value = {"keys": [rsa_keypair["jwk"]]}
        real_response.raise_for_status.return_value = None

        mocker.patch(
            "sbomify.apps.oidc.utils.requests.get",
            side_effect=[stale_response, real_response],
        )

        token = github_claims_factory()
        claims = verify_github_oidc_token(token)
        assert claims["repository"] == "acme/widget"


class TestCacheHardening:
    """Regressions for security finding H-1 (P1-A): JWKS cache poisoning."""

    def test_poisoned_cache_entry_rejected(self, mocker, rsa_keypair) -> None:
        """A pre-existing cache entry that fails structural validation must
        be DISCARDED — not handed to PyJWK. Otherwise an attacker who
        poisoned the cache could plant a forged signing key.
        """
        from django.core.cache import cache

        # Plant a poisoned entry: missing required 'n' (modulus). Looks
        # like JWKS shape on the surface but fails _is_valid_signing_jwk.
        poisoned = {"keys": [{"kty": "RSA", "kid": "test-kid-1", "e": "AQAB"}]}
        cache.set("sbomify:trusted:oidc:github:jwks", poisoned, timeout=3600)
        cache.delete("sbomify:trusted:oidc:github:jwks:last_refresh")

        # The next call should NOT trust the poisoned entry; it should
        # refetch — verify by mocking the upstream call.
        real_response = MagicMock()
        real_response.json.return_value = {"keys": [rsa_keypair["jwk"]]}
        real_response.raise_for_status.return_value = None
        get_mock = mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=real_response)

        from sbomify.apps.oidc.utils import _fetch_github_jwks

        result = _fetch_github_jwks()
        assert result == {"keys": [rsa_keypair["jwk"]]}
        get_mock.assert_called_once()  # refetched

    def test_undersize_modulus_rejected(self, mocker, rsa_keypair) -> None:
        """JWKs with a modulus under 2048 bits must be rejected."""
        from django.core.cache import cache

        cache.delete("sbomify:trusted:oidc:github:jwks")
        cache.delete("sbomify:trusted:oidc:github:jwks:last_refresh")
        # Real shape, but `n` is shortened to ~100 bits — far below minimum
        short = dict(rsa_keypair["jwk"])
        short["n"] = "abcd"
        weak_response = MagicMock()
        weak_response.json.return_value = {"keys": [short]}
        weak_response.raise_for_status.return_value = None
        mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=weak_response)

        with pytest.raises(OIDCJWKSUnavailable):
            verify_github_oidc_token("dummy.token.here")

    def test_redirects_disabled_on_jwks_fetch(self, mocker, rsa_keypair) -> None:
        """``requests.get`` must be called with ``allow_redirects=False`` —
        SSRF defense against a maliciously-redirecting JWKS host.
        """
        from django.core.cache import cache

        cache.delete("sbomify:trusted:oidc:github:jwks")
        cache.delete("sbomify:trusted:oidc:github:jwks:last_refresh")
        resp = MagicMock()
        resp.json.return_value = {"keys": [rsa_keypair["jwk"]]}
        resp.raise_for_status.return_value = None
        get_mock = mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=resp)

        from sbomify.apps.oidc.utils import _fetch_github_jwks

        _fetch_github_jwks()

        get_mock.assert_called_once()
        assert get_mock.call_args.kwargs.get("allow_redirects") is False

    def test_kid_miss_refresh_rate_limited(self, mocker, github_claims_factory, rsa_keypair) -> None:
        """Repeated kid-miss tokens must NOT trigger more than one refresh
        within the rate-limit window — DoS amplification defense.
        """
        from django.core.cache import cache

        cache.delete("sbomify:trusted:oidc:github:jwks")
        cache.delete("sbomify:trusted:oidc:github:jwks:last_refresh")

        # First fetch warms the cache with a JWK whose kid doesn't match.
        other_jwk = dict(rsa_keypair["jwk"])
        other_jwk["kid"] = "not-our-kid"
        stale_response = MagicMock()
        stale_response.json.return_value = {"keys": [other_jwk]}
        stale_response.raise_for_status.return_value = None

        # The kid-miss refresh would ALSO miss (same wrong key returned).
        get_mock = mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=stale_response)

        # Build a token with the real kid (which is NOT in any JWKS we'll serve).
        token = github_claims_factory()

        # First call: warm cache (1 fetch) + kid-miss refresh (2nd fetch).
        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(token)
        first_call_count = get_mock.call_count
        assert first_call_count == 2

        # Second call WITHIN the rate-limit window: the kid-miss path
        # should be SKIPPED (no additional fetch) since the refresh
        # marker is still live. The cached (still-stale) entry is reused.
        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(token)
        assert get_mock.call_count == first_call_count, (
            f"Forced JWKS refresh fired again within rate-limit window "
            f"(call_count {get_mock.call_count}, was {first_call_count})"
        )


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
