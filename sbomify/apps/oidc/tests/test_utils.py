"""Unit tests for ``sbomify.apps.oidc.utils.verify_github_oidc_token``."""

from __future__ import annotations

import time
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


class TestClockSkewLeeway:
    """GitHub's issuer clock can run a few seconds ahead of the verifier, so a
    freshly minted token's ``iat``/``nbf`` is often slightly in the *future* at
    verification time. With PyJWT's default ``leeway=0`` this raises
    ``ImmatureSignatureError`` ("not yet valid"), which the verifier remaps to a
    401 — failing every exchange. The verifier must tolerate a small clock skew.
    """

    @pytest.fixture(autouse=True)
    def _pin_leeway(self, settings) -> None:
        # Pin the leeway so these tests are deterministic regardless of any
        # OIDC_GITHUB_LEEWAY_SECONDS env override: 30s of skew is within it,
        # 3600s is well beyond it.
        settings.OIDC_GITHUB_LEEWAY_SECONDS = 60

    def test_iat_slightly_in_future_is_accepted(self, github_claims_factory, mock_github_jwks) -> None:
        now = int(time.time())
        token = github_claims_factory(iat=now + 30)
        claims = verify_github_oidc_token(token)
        assert claims["repository"] == "acme/widget"

    def test_nbf_slightly_in_future_is_accepted(self, github_claims_factory, mock_github_jwks) -> None:
        now = int(time.time())
        token = github_claims_factory(nbf=now + 30)
        claims = verify_github_oidc_token(token)
        assert claims["repository"] == "acme/widget"

    def test_far_future_beyond_leeway_still_rejected(self, github_claims_factory, mock_github_jwks) -> None:
        now = int(time.time())
        token = github_claims_factory(iat=now + 3600, nbf=now + 3600, exp=now + 7200)
        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(token)


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

    def test_double_miss_after_refresh_permanently_fails(
        self, mocker, github_claims_factory, rsa_keypair
    ) -> None:
        """Regression for test-automator P0: if both the initial fetch AND
        the forced refresh return JWKS without the token's kid, the call
        must fail with ``OIDCInvalidSignature("no JWK matches")`` — not
        retry forever.
        """
        from django.core.cache import cache

        cache.delete("sbomify:trusted:oidc:github:jwks")
        cache.delete("sbomify:trusted:oidc:github:jwks:last_refresh")

        wrong_jwk = dict(rsa_keypair["jwk"])
        wrong_jwk["kid"] = "wrong-kid"
        bad_response = MagicMock()
        bad_response.json.return_value = {"keys": [wrong_jwk]}
        bad_response.raise_for_status.return_value = None
        mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=bad_response)

        token = github_claims_factory()  # default kid="test-kid-1"
        with pytest.raises(OIDCInvalidSignature, match="no JWK matches"):
            verify_github_oidc_token(token)

    def test_alg_none_rejected(self, rsa_keypair, mock_github_jwks) -> None:
        """A JWT with ``alg=none`` (the classic JWT vulnerability) MUST
        be rejected. PyJWT 2.x refuses ``none`` by default AND the
        ``algorithms=["RS256"]`` whitelist excludes it — this test pins
        both layers.
        """
        # alg=none tokens have no signature; PyJWT refuses to even encode them
        # by default, so we hand-construct the JWT.
        import base64
        import json as json_mod

        header = base64.urlsafe_b64encode(
            json_mod.dumps({"alg": "none", "kid": "test-kid-1", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json_mod.dumps(
                {
                    "iss": "https://token.actions.githubusercontent.com",
                    "aud": "sbomify.com",
                    "exp": int(time.time()) + 60,
                    "iat": int(time.time()),
                    "sub": "x",
                }
            ).encode()
        ).rstrip(b"=").decode()
        unsigned_token = f"{header}.{payload}."

        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(unsigned_token)

    def test_hs256_confusion_attack_rejected(self, rsa_keypair, mock_github_jwks) -> None:
        """Classic alg-confusion attack: a token whose header claims
        ``alg=HS256``. If accepted, the verifier would try HMAC against
        the RSA public key bytes (which an attacker can fetch from JWKS),
        and the attacker's HMAC signature would verify. Our
        ``algorithms=["RS256"]`` whitelist prevents this.

        Modern PyJWT (≥2.x) ALSO refuses to encode HS* tokens using a
        PEM-formatted RSA key as the secret (raises InvalidKeyError),
        so the attacker has to hand-construct the token bytes. We do
        that here and assert our verifier rejects it.
        """
        import base64
        import hashlib
        import hmac
        import json as json_mod

        # Hand-construct an alg=HS256 JWT WITHOUT going through PyJWT's
        # encode (which refuses RSA-key-as-HMAC-secret in 2.x).
        header = base64.urlsafe_b64encode(
            json_mod.dumps({"alg": "HS256", "kid": "test-kid-1", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json_mod.dumps(
                {
                    "iss": "https://token.actions.githubusercontent.com",
                    "aud": "sbomify.com",
                    "exp": int(time.time()) + 60,
                    "iat": int(time.time()),
                    "sub": "x",
                }
            ).encode()
        ).rstrip(b"=").decode()
        signing_input = f"{header}.{payload}".encode()
        # The attacker uses the public key (which they can fetch from JWKS) as
        # the HMAC secret. We simulate that by using a stand-in secret —
        # the exact bytes don't matter because our verifier should refuse
        # alg=HS256 outright before the signature is checked.
        fake_secret = b"attacker-derived-from-public-key"
        signature = hmac.new(fake_secret, signing_input, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        confused = f"{header}.{payload}.{sig_b64}"

        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(confused)

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

    def test_future_iat_rejected(self, github_claims_factory, mock_github_jwks) -> None:
        """``iat`` (issued-at) in the future is impossible for a legitimate
        token — defends against attacker-minted tokens with a forward-dated
        ``iat`` (e.g. an attempt to extend usable window). PyJWT enforces
        this only when ``verify_iat=True`` is passed; pin the behaviour
        so a future refactor doesn't drop the option.
        """
        future = int(time.time()) + 600
        token = github_claims_factory(iat=future, exp=future + 60)
        with pytest.raises(OIDCInvalidSignature):
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

    def test_jwks_malformed_json_raises_unavailable(self, mocker) -> None:
        """Upstream returning non-JSON (HTML error page, truncated body)
        must map to ``OIDCJWKSUnavailable`` (503) — without this the
        unhandled ``ValueError`` bubbled to the exchange endpoint as a
        500 and exposed an internal failure to attackers.
        """
        from django.core.cache import cache

        cache.delete("sbomify:trusted:oidc:github:jwks")
        fake_response = mocker.MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
        mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=fake_response)
        with pytest.raises(OIDCJWKSUnavailable, match="not parseable"):
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

    def test_ssrf_guard_rejects_non_allowlisted_host(self, mocker, settings, rsa_keypair) -> None:
        """If ``OIDC_GITHUB_JWKS_URL`` env var is compromised to point at
        an internal address, the SSRF guard MUST reject before any HTTP
        is dispatched.
        """
        from django.core.cache import cache

        cache.delete("sbomify:trusted:oidc:github:jwks")
        settings.OIDC_GITHUB_JWKS_URL = "http://169.254.169.254/latest/meta-data/"
        get_mock = mocker.patch("sbomify.apps.oidc.utils.requests.get")

        with pytest.raises(OIDCJWKSUnavailable, match="not allow-listed"):
            verify_github_oidc_token("dummy.token.here")
        get_mock.assert_not_called()  # no HTTP attempted

    def test_ssrf_guard_rejects_http_scheme(self, mocker, settings, rsa_keypair) -> None:
        """Even with the correct host, ``http://`` (non-TLS) is rejected."""
        from django.core.cache import cache

        cache.delete("sbomify:trusted:oidc:github:jwks")
        settings.OIDC_GITHUB_JWKS_URL = "http://token.actions.githubusercontent.com/.well-known/jwks"
        get_mock = mocker.patch("sbomify.apps.oidc.utils.requests.get")

        with pytest.raises(OIDCJWKSUnavailable, match="not allow-listed"):
            verify_github_oidc_token("dummy.token.here")
        get_mock.assert_not_called()

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
