"""A one-hour cache in front of a network is a scheduled outage.

The JWKS entry expires after an hour, and there was nothing behind it. Any
moment GitHub was unreachable after that expiry failed every OIDC exchange
that arrived, with a 503 apiece. From staging, inside a single minute:

    GitHub JWKS fetch failed (...): [Errno 113] No route to host
    Service Unavailable: /api/v1/auth/oidc/github/exchange

— eleven consecutive CI token exchanges, none of which had anything wrong
with them, failed because of a network fault that lasted less time than the
log line took to write.

Every successful fetch now also writes a longer-lived last-known-good copy,
served when GitHub cannot be reached. The trade is bounded staleness: while
GitHub is unreachable we keep trusting keys it may since have retired. Key
rotation is a planned, pre-announced event and a retired key stays valid
upstream far longer than a day; a thirty-second network fault is routine.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests
from django.core.cache import cache

from sbomify.apps.oidc.utils import (
    _JWKS_CACHE_KEY,
    _JWKS_FETCH_BACKOFF_KEY,
    _JWKS_REFRESH_MARKER_KEY,
    _JWKS_FALLBACK_CACHE_KEY,
    OIDCJWKSUnavailable,
    _fetch_github_jwks,
    verify_github_oidc_token,
)


def _unreachable(mocker) -> Any:
    """GitHub not answering, which is what staging actually saw."""
    return mocker.patch(
        "sbomify.apps.oidc.utils.requests.get",
        side_effect=requests.exceptions.ConnectionError("[Errno 113] No route to host"),
    )


def _expire_the_fresh_entry() -> None:
    """The 1h entry lapsing, without waiting an hour for it."""
    cache.delete(_JWKS_CACHE_KEY)


def _backoff_expiry() -> float:
    """When the backoff marker lapses.

    Reaches into LocMemCache's expiry table because Django's cache API has no
    public way to read a key's remaining life, and the distinction being tested
    — set the window once, versus restart it on every request — is invisible in
    the value itself.
    """
    return cache._expire_info[cache.make_key(_JWKS_FETCH_BACKOFF_KEY)]


def _cold_cache() -> None:
    """A deployment that has never reached GitHub.

    Deletes the three JWKS slots by name rather than calling ``cache.clear()``:
    the cache is shared with throttle windows and checkout locks, and wiping it
    from inside one test is how neighbouring tests start failing for reasons
    that have nothing to do with them.
    """
    cache.delete(_JWKS_CACHE_KEY)
    cache.delete(_JWKS_FALLBACK_CACHE_KEY)
    cache.delete(_JWKS_REFRESH_MARKER_KEY)
    cache.delete(_JWKS_FETCH_BACKOFF_KEY)


class TestTheFallbackCarriesTheOutage:
    def test_a_successful_fetch_records_a_fallback(self, mock_github_jwks, rsa_keypair) -> None:
        """Nothing else works if this does not happen on the success path."""
        _fetch_github_jwks()

        assert cache.get(_JWKS_FALLBACK_CACHE_KEY) == {"keys": [rsa_keypair["jwk"]]}

    def test_an_unreachable_github_is_survived(self, mocker, mock_github_jwks, rsa_keypair) -> None:
        """The defect: this raised, and every exchange behind it became a 503."""
        _fetch_github_jwks()  # populates both entries
        _expire_the_fresh_entry()
        _unreachable(mocker)

        assert _fetch_github_jwks() == {"keys": [rsa_keypair["jwk"]]}

    def test_a_real_token_still_verifies_during_the_outage(
        self, mocker, mock_github_jwks, github_claims_factory
    ) -> None:
        """The point of the whole change, at the level the user experiences:
        a CI job exchanging a perfectly good token mid-blip should not be told
        the service is unavailable."""
        token = github_claims_factory()
        verify_github_oidc_token(token)  # warms the fallback
        _expire_the_fresh_entry()
        _unreachable(mocker)

        assert verify_github_oidc_token(github_claims_factory())["iss"]

    def test_a_malformed_upstream_body_also_falls_back(self, mocker, mock_github_jwks, rsa_keypair) -> None:
        """GitHub's edge serving an HTML error page with a 200 is the same
        outage wearing a different hat."""
        _fetch_github_jwks()
        _expire_the_fresh_entry()
        bad = mocker.MagicMock()
        bad.raise_for_status.return_value = None
        bad.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
        mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=bad)

        assert _fetch_github_jwks() == {"keys": [rsa_keypair["jwk"]]}


class TestWithoutAFallbackNothingChanges:
    def test_a_cold_cache_still_raises(self, mocker) -> None:
        """A deployment that has never reached GitHub has nothing to serve, and
        must still fail loudly rather than inventing something."""
        _cold_cache()
        _unreachable(mocker)

        with pytest.raises(OIDCJWKSUnavailable):
            _fetch_github_jwks()

    def test_the_original_error_is_what_surfaces(self, mocker) -> None:
        """The 503 an operator sees should still name the cause."""
        _cold_cache()
        _unreachable(mocker)

        with pytest.raises(OIDCJWKSUnavailable, match="No route to host"):
            _fetch_github_jwks()


class TestTheFallbackIsNotATrustHole:
    """Serving something stale must not mean serving something unchecked."""

    def test_a_poisoned_fallback_is_discarded(self, mocker, rsa_keypair) -> None:
        """The fresh entry is structurally revalidated on read precisely
        because an attacker in the cache could otherwise plant a key whose
        private half they hold. A fallback read without the same check would
        reopen that, with a longer window than the one it closed."""
        _cold_cache()
        cache.set(_JWKS_FALLBACK_CACHE_KEY, {"keys": [{"kty": "RSA", "kid": "evil", "n": "AQAB", "e": "AQAB"}]})
        _unreachable(mocker)

        with pytest.raises(OIDCJWKSUnavailable):
            _fetch_github_jwks()

    def test_a_poisoned_fallback_is_evicted_not_left_to_be_retried(self, mocker) -> None:
        _cold_cache()
        cache.set(_JWKS_FALLBACK_CACHE_KEY, {"not": "a jwks"})
        _unreachable(mocker)

        with pytest.raises(OIDCJWKSUnavailable):
            _fetch_github_jwks()

        assert cache.get(_JWKS_FALLBACK_CACHE_KEY) is None

    def test_a_token_signed_by_an_unknown_key_still_fails_during_an_outage(
        self, mocker, mock_github_jwks, github_claims_factory, rsa_keypair
    ) -> None:
        """The fallback relaxes how recently we spoke to GitHub, nothing else.
        A signature that does not verify against it is still rejected."""
        from sbomify.apps.oidc.utils import OIDCInvalidSignature

        verify_github_oidc_token(github_claims_factory())  # warms the fallback
        _expire_the_fresh_entry()
        _unreachable(mocker)

        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa

        attacker_key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(
            jwt.decode(github_claims_factory(), options={"verify_signature": False}),
            attacker_key,
            algorithm="RS256",
            headers={"kid": rsa_keypair["jwk"]["kid"]},
        )

        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(forged)


class TestTheFreshPathIsPreferred:
    def test_a_reachable_github_is_still_used(self, mocker, mock_github_jwks, rsa_keypair) -> None:
        """The fallback is for outages. A working fetch must not be shadowed by
        a stale copy, or a rotation would never be picked up."""
        cache.set(_JWKS_FALLBACK_CACHE_KEY, {"keys": [dict(rsa_keypair["jwk"], kid="stale-kid")]})
        _expire_the_fresh_entry()

        assert _fetch_github_jwks()["keys"][0]["kid"] == rsa_keypair["jwk"]["kid"]

    def test_the_fallback_is_refreshed_by_each_success(self, mocker, mock_github_jwks, rsa_keypair) -> None:
        """So the copy served during an outage is from the last time GitHub was
        reachable, not from whenever it was first seen."""
        cache.set(_JWKS_FALLBACK_CACHE_KEY, {"keys": [dict(rsa_keypair["jwk"], kid="older-kid")]})
        _expire_the_fresh_entry()

        _fetch_github_jwks()

        assert cache.get(_JWKS_FALLBACK_CACHE_KEY)["keys"][0]["kid"] == rsa_keypair["jwk"]["kid"]


class TestAKidMissDuringAnOutageIsNotTheTokensFault:
    """The fallback answers with the document that was already in hand, so a
    kid it does not contain proves nothing about the token — GitHub may have
    rotated the key in and we simply could not ask."""

    def test_it_reports_unavailable_rather_than_invalid(self, mocker, mock_github_jwks, github_claims_factory) -> None:
        """401 told a CI client its token was rejected, so it stopped retrying
        a condition that would clear on its own, and sent whoever investigated
        looking at the customer's workflow instead of at the outage."""
        import jwt

        verify_github_oidc_token(github_claims_factory())  # warms the fallback
        _expire_the_fresh_entry()
        _unreachable(mocker)

        rotated = jwt.encode(
            jwt.decode(github_claims_factory(), options={"verify_signature": False}),
            "secret",
            algorithm="HS256",
            headers={"kid": "a-kid-github-rotated-in-while-we-were-blind"},
        )

        with pytest.raises(OIDCJWKSUnavailable):
            verify_github_oidc_token(rotated)

    def test_a_kid_miss_against_fresh_keys_is_still_invalid(self, mock_github_jwks, github_claims_factory) -> None:
        """The half that must not change: when GitHub answered and the key is
        genuinely not there, the token really is unverifiable."""
        import jwt

        from sbomify.apps.oidc.utils import OIDCInvalidSignature

        unknown = jwt.encode(
            jwt.decode(github_claims_factory(), options={"verify_signature": False}),
            "secret",
            algorithm="HS256",
            headers={"kid": "never-existed"},
        )

        with pytest.raises(OIDCInvalidSignature):
            verify_github_oidc_token(unknown)


class TestTheMalformedBodyBranchIsReachable:
    def test_a_real_requests_json_error_takes_the_parse_branch(self, mocker, mock_github_jwks, rsa_keypair) -> None:
        """requests' JSONDecodeError inherits from RequestException, so the
        broader handler used to swallow every malformed body and the parse
        branch was dead — its tests passed only because their mock raised a
        bare ValueError, which no real response produces."""
        _fetch_github_jwks()
        _expire_the_fresh_entry()

        bad = mocker.MagicMock()
        bad.raise_for_status.return_value = None
        bad.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)
        mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=bad)

        assert _fetch_github_jwks() == {"keys": [rsa_keypair["jwk"]]}

    def test_it_names_the_parse_failure_when_there_is_no_fallback(self, mocker) -> None:
        _cold_cache()
        bad = mocker.MagicMock()
        bad.raise_for_status.return_value = None
        bad.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)
        mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=bad)

        with pytest.raises(OIDCJWKSUnavailable, match="not parseable"):
            _fetch_github_jwks()


class TestServingTheFallbackIsAnnounced:
    """The absence of this test is why the log line silently became dead code.

    An edit left it indented inside the invalid-entry branch, after the raise,
    so the fallback was served with nothing written anywhere — the deployment
    would have been running on stale keys with no signal at all, which is the
    opposite of what this whole change is for.
    """

    def test_a_warning_names_the_condition(self, mocker, mock_github_jwks) -> None:
        from sbomify.apps.oidc import utils as oidc_utils

        _fetch_github_jwks()
        _expire_the_fresh_entry()
        _unreachable(mocker)

        # mocker.patch.object returns the mock itself, not a context manager.
        warning = mocker.patch.object(oidc_utils.logger, "warning")
        _fetch_github_jwks()

        assert any("last-known-good" in call.args[0] for call in warning.call_args_list)

    def test_a_fresh_fetch_says_nothing(self, mocker, mock_github_jwks) -> None:
        """It must not fire on the ordinary path, or it stops meaning anything."""
        from sbomify.apps.oidc import utils as oidc_utils

        warning = mocker.patch.object(oidc_utils.logger, "warning")
        _fetch_github_jwks()

        assert not [c for c in warning.call_args_list if "last-known-good" in c.args[0]]


class TestAnOutageDoesNotCostAFetchPerRequest:
    """The fallback was correct but slow in exactly the case it exists for.

    With the fresh entry gone, every exchange re-ran the fetch and blocked for
    the full timeout before being handed the copy we already had. A CI fleet
    doing concurrent exchanges holds a worker each for that long, so an outage
    at GitHub became saturation here — the fast 503 the fallback replaced at
    least freed the worker.
    """

    def test_a_second_exchange_does_not_refetch(self, mocker, mock_github_jwks, rsa_keypair) -> None:
        _fetch_github_jwks()  # warms the fallback
        _expire_the_fresh_entry()
        get = _unreachable(mocker)

        assert _fetch_github_jwks() == {"keys": [rsa_keypair["jwk"]]}
        first = get.call_count
        assert _fetch_github_jwks() == {"keys": [rsa_keypair["jwk"]]}

        assert get.call_count == first, "second exchange paid for another doomed fetch"

    def test_recovery_is_picked_up_once_the_backoff_lapses(self, mocker, mock_github_jwks, rsa_keypair) -> None:
        """Suppressed, not abandoned — GitHub coming back has to be noticed."""
        _fetch_github_jwks()
        _expire_the_fresh_entry()
        _unreachable(mocker)
        _fetch_github_jwks()

        cache.delete(_JWKS_FETCH_BACKOFF_KEY)  # stands in for the marker expiring
        mocker.stopall()
        rotated = {"keys": [dict(rsa_keypair["jwk"], kid="rotated-in-during-the-outage")]}
        response = mocker.MagicMock()
        response.json.return_value = rotated
        response.raise_for_status.return_value = None
        mocker.patch("sbomify.apps.oidc.utils.requests.get", return_value=response)

        assert _fetch_github_jwks() == rotated

    def test_traffic_during_the_outage_does_not_extend_the_window(
        self, mocker, mock_github_jwks, rsa_keypair
    ) -> None:
        """The window is measured from the first failure, not from the last request.

        Every exchange served from the fallback comes back through the arming
        site, so re-stamping the marker there would push its expiry out again
        each time. Under steady traffic — which is the load this exists for —
        the window would then never close and the recovery above would never
        be reached.
        """
        _fetch_github_jwks()
        _expire_the_fresh_entry()
        _unreachable(mocker)
        _fetch_github_jwks()
        first_expiry = _backoff_expiry()

        for _ in range(3):
            _fetch_github_jwks()

        assert _backoff_expiry() == first_expiry, "continued traffic pushed the retry further away"

    def test_a_cold_cache_still_tries(self, mocker) -> None:
        """With nothing to fall back to, failing fast would fail every request
        without ever attempting the fetch."""
        _cold_cache()
        get = _unreachable(mocker)

        with pytest.raises(OIDCJWKSUnavailable):
            _fetch_github_jwks()

        assert get.call_count > 0

    def test_a_successful_fetch_clears_the_backoff(self, mocker, mock_github_jwks) -> None:
        _fetch_github_jwks()

        assert cache.get(_JWKS_FETCH_BACKOFF_KEY) is None
