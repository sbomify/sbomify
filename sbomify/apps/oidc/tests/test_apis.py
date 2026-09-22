"""Integration tests for the GitHub OIDC token-exchange endpoint."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.oidc.github_api import GitHubResolveError, ResolvedRepository
from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.services import provision_bot_user_for_binding
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team

EXCHANGE_URL = "/api/v1/auth/oidc/github/exchange"
BINDINGS_URL = "/api/v1/auth/oidc/github/bindings"


@pytest.fixture
def component(db, team_with_business_plan: Team) -> Component:
    return Component.objects.create(name="OIDC Exchange Test", team=team_with_business_plan)


@pytest.fixture
def github_binding(component: Component, sample_user):
    """A fully-provisioned binding for ``acme/widget`` (owner_id=67890, repo_id=12345)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    placeholder = User.objects.create_user(username="placeholder-exchange", password="x")
    binding = OIDCBinding.objects.create(
        component=component,
        provider=OIDCBinding.PROVIDER_GITHUB,
        repository="acme/widget",
        repository_id=12345,
        repository_owner_id=67890,
        bot_user=placeholder,
        created_by=sample_user,
    )
    bot = provision_bot_user_for_binding(binding)
    binding.bot_user = bot
    binding.save(update_fields=["bot_user"])
    return binding


class TestClockSkewExchange:
    """End-to-end reproduction of the production failure through the real
    exchange endpoint: when GitHub's issuer clock runs ahead of the verifier, a
    fresh token's ``iat``/``nbf`` is slightly in the future. With the old
    ``leeway=0`` every exchange 401'd ("Last used: never"); with the clock-skew
    leeway the full path (verify → coerce → binding lookup → mint) must succeed.
    """

    @pytest.fixture(autouse=True)
    def _pin_leeway(self, settings) -> None:
        # Deterministic regardless of any OIDC_GITHUB_LEEWAY_SECONDS env override.
        settings.OIDC_GITHUB_LEEWAY_SECONDS = 60

    @pytest.mark.django_db
    def test_future_iat_nbf_token_still_exchanges(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        now = int(time.time())
        # Simulate GitHub's issuer clock ~30s ahead of ours -> future iat/nbf.
        token = github_claims_factory(
            repository_owner_id=67890, repository_id=12345, iat=now + 30, nbf=now + 30
        )
        response = Client().post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 200, response.content
        assert "access_token" in response.json()

    @pytest.mark.django_db
    def test_zero_leeway_rejects_future_token(
        self, settings, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """Anchors the root cause: with no leeway (the old behavior) the very same
        future-iat/nbf token is rejected by the endpoint with 401 — the exact
        production failure this fix removes."""
        settings.OIDC_GITHUB_LEEWAY_SECONDS = 0
        now = int(time.time())
        token = github_claims_factory(
            repository_owner_id=67890, repository_id=12345, iat=now + 30, nbf=now + 30
        )
        response = Client().post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401, response.content


class TestSuccessfulExchange:
    @pytest.mark.django_db
    def test_returns_short_lived_token_and_creates_db_row(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        token = github_claims_factory(repository_owner_id=67890, repository_id=12345)
        client = Client()

        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert "access_token" in body
        assert body["expires_in"] == 900
        assert body["component_id"] == component.id

        # AccessToken row exists with expires_at set ~15 min out, owned by bot
        row = AccessToken.objects.get(encoded_token=body["access_token"])
        assert row.user_id == github_binding.bot_user_id
        assert row.team_id == component.team_id
        assert row.expires_at is not None
        from django.utils import timezone

        delta = (row.expires_at - timezone.now()).total_seconds()
        assert 870 < delta <= 900, f"expires_at not ~15 min out, got delta={delta}"

    @pytest.mark.django_db
    def test_updates_binding_last_used_at(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        assert github_binding.last_used_at is None
        token = github_claims_factory(repository_owner_id=67890, repository_id=12345)
        client = Client()
        client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        github_binding.refresh_from_db()
        assert github_binding.last_used_at is not None

    @pytest.mark.django_db
    def test_replay_within_ttl_succeeds_twice(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """Test-automator P0: two POSTs with the SAME OIDC token within
        TTL should each succeed and mint distinct AccessToken rows.

        OIDC tokens are short-lived (5-15 min) so reusing one inside its
        own TTL is legitimate (CI retry, parallel job within one workflow
        run). Pinning this means a future "one-shot OIDC token" change
        has to update this test deliberately.
        """
        token = github_claims_factory(repository_owner_id=67890, repository_id=12345)
        client = Client()
        body = json.dumps({"component_id": component.id})
        headers = {"content_type": "application/json", "HTTP_AUTHORIZATION": f"Bearer {token}"}

        r1 = client.post(EXCHANGE_URL, data=body, **headers)
        r2 = client.post(EXCHANGE_URL, data=body, **headers)

        assert r1.status_code == 200
        assert r2.status_code == 200
        # Distinct sbomify tokens — each call mints its own with fresh
        # salt + timestamp.
        assert r1.json()["access_token"] != r2.json()["access_token"]
        assert AccessToken.objects.filter(user_id=github_binding.bot_user_id).count() == 2

    @pytest.mark.django_db
    def test_failed_exchange_does_not_bump_last_used_at(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """Test-automator P1: a 403 (unbound repo) must NOT update
        ``binding.last_used_at`` — only successful exchanges count.
        """
        assert github_binding.last_used_at is None
        token = github_claims_factory(repository="evil/forge", repository_owner_id=11111, repository_id=22222)
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 403
        github_binding.refresh_from_db()
        assert github_binding.last_used_at is None, (
            "Refused-token exchange must NOT bump last_used_at — the timestamp is a 'last legitimate use' indicator."
        )


class TestRequestValidation:
    @pytest.mark.django_db
    def test_missing_authorization_header_400(self, mock_github_jwks, github_binding, component) -> None:
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Authorization" in response.json()["detail"]

    @pytest.mark.django_db
    def test_non_bearer_scheme_400(self, mock_github_jwks, github_binding, component) -> None:
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Basic abc=",
        )
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_missing_component_id_400(self, github_claims_factory, mock_github_jwks, github_binding) -> None:
        token = github_claims_factory()
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": ""}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 400

    @pytest.mark.django_db
    def test_unknown_component_404(self, github_claims_factory, mock_github_jwks) -> None:
        token = github_claims_factory()
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": "does_not_exist"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 404


class TestTokenRejection:
    """Every variety of bad OIDC token must yield 401 with the SAME body.

    The detail string is intentionally generic so a forger can't probe
    which check failed (signature vs. issuer vs. audience).
    """

    @pytest.mark.django_db
    def test_forged_signature_401(self, mock_github_jwks, github_binding, component) -> None:
        attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = pyjwt.encode(
            {
                "iss": "https://token.actions.githubusercontent.com",
                "aud": "sbomify.com",
                "exp": time.time() + 60,
                "iat": time.time(),
                "sub": "x",
                "repository_owner_id": 67890,
                "repository_id": 12345,
            },
            attacker.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            algorithm="RS256",
            headers={"kid": "test-kid-1"},
        )
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {forged}",
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid OIDC token"

    @pytest.mark.django_db
    def test_wrong_audience_401_with_sparse_body(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        token = github_claims_factory(aud="some-other-service")
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        # ``detail`` MUST match the forged-signature body verbatim —
        # sparseness is a security property (don't leak which sub-check
        # failed). Other ErrorResponse fields can vary.
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid OIDC token"

    @pytest.mark.django_db
    def test_expired_token_401_with_sparse_body(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        token = github_claims_factory(exp=int(time.time()) - 60, iat=int(time.time()) - 120)
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid OIDC token"

    @pytest.mark.django_db
    def test_missing_repository_id_claims_401(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """A token that's valid but lacks repository_id / repository_owner_id
        must NOT match any binding — return 401 (not 403) since the token
        itself is missing the claim we depend on.
        """
        token = github_claims_factory(repository_owner_id=None, repository_id=None)
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401

    @pytest.mark.django_db
    def test_string_repository_id_claims_succeed(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """Real GitHub tokens encode ``repository_id`` and
        ``repository_owner_id`` as JSON strings (``"74"``, not ``74``).

        Regression for the production 401-loop where every exchange was
        rejected because the service-layer typecheck required Python
        ``int`` — see services._coerce_repo_int_claim.
        """
        token = github_claims_factory(repository_owner_id="67890", repository_id="12345")
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 200, response.content

    @pytest.mark.django_db
    def test_non_numeric_string_repository_id_401(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """A non-numeric string in ``repository_id`` must still 401.

        Accepting strings (to mirror GitHub) shouldn't open the door to
        forged tokens with arbitrary payloads in the ID claim.
        """
        token = github_claims_factory(repository_owner_id="67890", repository_id="not-a-number")
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid OIDC token"

    @pytest.mark.django_db
    def test_bool_repository_id_claim_rejected(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """``bool`` is an ``int`` subclass in Python — ``int(True) == 1``.

        Without an explicit reject, a forged token with
        ``"repository_id": true`` would silently coerce to ``1`` and
        attempt a binding lookup. Belt-and-suspenders: reject explicitly.
        """
        token = github_claims_factory(repository_owner_id=True, repository_id=True)
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "bad_value",
        [
            "  12345  ",  # whitespace
            "+12345",  # positive sign
            "-12345",  # negative
            "1_2345",  # PEP 515 underscore separator
            "12345.0",  # decimal
            "0x3039",  # hex
            "١٢٣٤٥",  # Arabic-Indic digits (decimal, but non-ASCII)
            "",  # empty
        ],
    )
    def test_non_canonical_string_repository_id_401(
        self, github_claims_factory, mock_github_jwks, github_binding, component, bad_value
    ) -> None:
        """GitHub emits ASCII-decimal-only strings; everything else 401.

        Python's ``int()`` is permissive (accepts whitespace, signs,
        PEP 515 underscores, and Unicode decimal digits) — the helper
        deliberately tightens to ``value.isascii() and value.isdigit()``
        to mirror GitHub's wire format exactly. Regression for
        defense-in-depth finding on the OIDC PR.
        """
        token = github_claims_factory(repository_owner_id="67890", repository_id=bad_value)
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401, response.content

    @pytest.mark.django_db
    def test_repository_id_overflowing_bigint_401(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """A value > 2**63-1 must 401, not 500.

        Python ints are unbounded, but ``OIDCBinding.repository_id`` is
        a PostgreSQL ``bigint``. Without the range check, the
        downstream ``filter(repository_id=<huge>)`` would raise
        ``DataError`` and propagate as an unhandled 500 — violating
        the documented 401-only-for-bad-token error contract.
        """
        too_big = str(2**63)  # one over int64 max
        token = github_claims_factory(repository_owner_id="67890", repository_id=too_big)
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401, response.content


class TestBindingMismatch:
    @pytest.mark.django_db
    def test_token_for_unbound_repo_403(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """Token is valid + component exists, but the (owner_id, repo_id)
        claim pair doesn't match any binding for this component → 403.
        """
        token = github_claims_factory(
            repository="evil/forge",
            repository_owner_id=99999,  # different owner
            repository_id=88888,  # different repo
        )
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 403
        assert "not bound" in response.json()["detail"]

    @pytest.mark.django_db
    def test_account_resurrection_attack_blocked(
        self, github_claims_factory, mock_github_jwks, github_binding, component
    ) -> None:
        """Same repository NAME but different owner_id (the resurrection
        scenario) must NOT pass the binding match.
        """
        # Binding pinned to owner_id=67890, repo_id=12345 (acme/widget original)
        # Attacker registered "acme/widget" under a different owner_id
        token = github_claims_factory(
            repository="acme/widget",  # same NAME
            repository_owner_id=11111,  # but different ID
            repository_id=22222,
        )
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 403


class TestRateLimit:
    """Regression for security finding H-2: the exchange endpoint MUST
    be rate-limited so an unauthenticated attacker can't:
    * enumerate component IDs cheaply (status leaks existence)
    * spam novel-kid tokens to amplify JWKS refresh
    * brute-force forged signatures
    """

    @pytest.mark.django_db
    def test_429_after_burst_from_same_ip(
        self, github_claims_factory, mock_github_jwks, github_binding, component, mocker
    ) -> None:
        # Patch the rate-limit group to a test-only namespace so its
        # counters live in a sandbox and we never collide with — or
        # need to ``cache.clear()`` — any other test's cache state.
        unique_group = f"oidc:github:exchange:test:{component.id}"
        mocker.patch("sbomify.apps.oidc.apis._EXCHANGE_RATE_LIMIT_GROUP", unique_group)
        mocker.patch("sbomify.apps.oidc.apis._EXCHANGE_RATE_LIMIT", "3/m")

        token = github_claims_factory(repository_owner_id=67890, repository_id=12345)
        client = Client()
        body = json.dumps({"component_id": component.id})
        headers = {
            "content_type": "application/json",
            "HTTP_AUTHORIZATION": f"Bearer {token}",
        }

        # First 3 requests within the window succeed (or hit some other
        # status — they're real exchanges) — we just need NONE of them
        # to be 429.
        statuses = []
        for _ in range(3):
            r = client.post(EXCHANGE_URL, data=body, **headers)
            statuses.append(r.status_code)
        assert 429 not in statuses

        # 4th request from the same IP within the same minute → 429
        r = client.post(EXCHANGE_URL, data=body, **headers)
        assert r.status_code == 429
        assert r.json()["detail"] == "too many requests"


class TestInfrastructureFailures:
    @pytest.mark.django_db
    def test_jwks_unavailable_503(self, github_claims_factory, github_binding, component, mocker, rsa_keypair) -> None:
        """GitHub's JWKS endpoint being down must NOT be conflated with a bad
        token — return 503 so CI doesn't retry-loop a real config error.
        """
        from django.core.cache import cache

        cache.delete("sbomify:trusted:oidc:github:jwks")
        mocker.patch(
            "sbomify.apps.oidc.utils.requests.get",
            side_effect=requests.exceptions.ConnectionError("dns boom"),
        )
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
            headers={"kid": "test-kid-1"},
        )
        client = Client()
        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 503


# ============================================================================
# Binding-management API: GET/POST/DELETE /api/v1/auth/oidc/github/bindings
#
# Authenticated (PAT or session), owner/admin-gated, thin dispatch over the
# same services the UI uses. resolve_repository (the GitHub REST call) is
# mocked so create tests don't hit the network. Permission failures conflate
# to 404 (anti-enumeration) — a non-owner can't tell "no such component" from
# "you can't manage this one".
# ============================================================================

_RESOLVED = ResolvedRepository(
    repository="acme/widget",
    repository_owner="acme",
    repository_id=12345,
    repository_owner_id=67890,
)


@pytest.fixture
def owned_component(sample_team_with_owner_member) -> Component:
    """A component in a workspace where ``sample_user`` is the owner."""
    return Component.objects.create(name="Binding API Test", team=sample_team_with_owner_member.team)


@pytest.mark.django_db
class TestBindingManagementCreate:
    def test_owner_creates_binding_201(self, authenticated_api_client, owned_component, mocker) -> None:
        mocker.patch("sbomify.apps.oidc.services.resolve_repository", return_value=_RESOLVED)
        client, token = authenticated_api_client

        response = client.post(
            BINDINGS_URL,
            data=json.dumps({"component_id": owned_component.id, "repository": "acme/widget"}),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["repository"] == "acme/widget"
        assert body["repository_id"] == 12345
        assert body["repository_owner_id"] == 67890
        assert body["provider"] == OIDCBinding.PROVIDER_GITHUB
        assert body["component_id"] == owned_component.id
        # Row persisted + bot user provisioned (so a later exchange works).
        binding = OIDCBinding.objects.get(pk=body["id"])
        assert binding.bot_user is not None

    def test_malformed_repository_400_no_network(self, authenticated_api_client, owned_component, mocker) -> None:
        """A slug that isn't 'org/repo' is rejected before any GitHub call."""
        resolve = mocker.patch("sbomify.apps.oidc.services.resolve_repository", side_effect=_RESOLVED)
        # resolve_repository validates the pattern itself and raises 'malformed';
        # patch it to the real behaviour for this one case so we exercise the 400.
        resolve.side_effect = GitHubResolveError("malformed", "bad slug")
        client, token = authenticated_api_client

        response = client.post(
            BINDINGS_URL,
            data=json.dumps({"component_id": owned_component.id, "repository": "not-a-valid-slug"}),
            content_type="application/json",
            **get_api_headers(token),
        )
        assert response.status_code == 400, response.content

    def test_duplicate_binding_409(self, authenticated_api_client, owned_component, mocker) -> None:
        mocker.patch("sbomify.apps.oidc.services.resolve_repository", return_value=_RESOLVED)
        client, token = authenticated_api_client
        body = json.dumps({"component_id": owned_component.id, "repository": "acme/widget"})

        first = client.post(BINDINGS_URL, data=body, content_type="application/json", **get_api_headers(token))
        assert first.status_code == 201
        second = client.post(BINDINGS_URL, data=body, content_type="application/json", **get_api_headers(token))
        assert second.status_code == 409, second.content

    def test_unknown_component_404(self, authenticated_api_client, mocker) -> None:
        mocker.patch("sbomify.apps.oidc.services.resolve_repository", return_value=_RESOLVED)
        client, token = authenticated_api_client
        response = client.post(
            BINDINGS_URL,
            data=json.dumps({"component_id": "does_not_exist", "repository": "acme/widget"}),
            content_type="application/json",
            **get_api_headers(token),
        )
        assert response.status_code == 404, response.content

    def test_unauthenticated_rejected(self, owned_component) -> None:
        """No credential → rejected. The dual-auth tuple is
        ``(PersonalAccessTokenAuth, django_auth)``; with no Bearer and no
        session, the session backend's CSRF check fires first on this unsafe
        method, so a live server returns 403. The test client disables CSRF
        enforcement, so here it surfaces as Ninja's 401. Either way it's
        rejected before any handler logic — accept both. (A real action call
        always presents a PAT, which authenticates via the Bearer path and
        never reaches the CSRF check.)"""
        client = Client()
        response = client.post(
            BINDINGS_URL,
            data=json.dumps({"component_id": owned_component.id, "repository": "acme/widget"}),
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_non_member_conflated_to_404(self, guest_api_client, owned_component, mocker) -> None:
        """A token whose user has NO role in the component's workspace gets 404,
        not 403 — same body as 'no such component' so inventory can't leak."""
        mocker.patch("sbomify.apps.oidc.services.resolve_repository", return_value=_RESOLVED)
        client, token = guest_api_client
        response = client.post(
            BINDINGS_URL,
            data=json.dumps({"component_id": owned_component.id, "repository": "acme/widget"}),
            content_type="application/json",
            **get_api_headers(token),
        )
        assert response.status_code == 404, response.content
        # And nothing was created.
        assert not OIDCBinding.objects.filter(component=owned_component).exists()


@pytest.mark.django_db
class TestBindingManagementListDelete:
    def _create(self, client, token, component, mocker) -> str:
        mocker.patch("sbomify.apps.oidc.services.resolve_repository", return_value=_RESOLVED)
        response = client.post(
            BINDINGS_URL,
            data=json.dumps({"component_id": component.id, "repository": "acme/widget"}),
            content_type="application/json",
            **get_api_headers(token),
        )
        assert response.status_code == 201, response.content
        return response.json()["id"]

    def test_list_returns_bindings(self, authenticated_api_client, owned_component, mocker) -> None:
        client, token = authenticated_api_client
        binding_id = self._create(client, token, owned_component, mocker)

        response = client.get(f"{BINDINGS_URL}?component_id={owned_component.id}", **get_api_headers(token))
        assert response.status_code == 200, response.content
        bindings = response.json()
        assert [b["id"] for b in bindings] == [binding_id]
        assert bindings[0]["repository"] == "acme/widget"

    def test_list_empty_for_component_without_bindings(self, authenticated_api_client, owned_component) -> None:
        client, token = authenticated_api_client
        response = client.get(f"{BINDINGS_URL}?component_id={owned_component.id}", **get_api_headers(token))
        assert response.status_code == 200
        assert response.json() == []

    def test_list_non_member_404(self, guest_api_client, owned_component) -> None:
        client, token = guest_api_client
        response = client.get(f"{BINDINGS_URL}?component_id={owned_component.id}", **get_api_headers(token))
        assert response.status_code == 404

    def test_delete_removes_binding_204(self, authenticated_api_client, owned_component, mocker) -> None:
        client, token = authenticated_api_client
        binding_id = self._create(client, token, owned_component, mocker)

        response = client.delete(
            f"{BINDINGS_URL}/{binding_id}?component_id={owned_component.id}", **get_api_headers(token)
        )
        assert response.status_code == 204, response.content
        assert not OIDCBinding.objects.filter(pk=binding_id).exists()

    def test_delete_unknown_binding_404(self, authenticated_api_client, owned_component) -> None:
        client, token = authenticated_api_client
        response = client.delete(
            f"{BINDINGS_URL}/does_not_exist?component_id={owned_component.id}", **get_api_headers(token)
        )
        assert response.status_code == 404

    def test_delete_non_member_404(self, guest_api_client, authenticated_api_client, owned_component, mocker) -> None:
        """A non-member can't delete another workspace's binding (404, and the
        binding survives)."""
        owner_client, owner_token = authenticated_api_client
        binding_id = self._create(owner_client, owner_token, owned_component, mocker)

        guest_client, guest_token = guest_api_client
        response = guest_client.delete(
            f"{BINDINGS_URL}/{binding_id}?component_id={owned_component.id}", **get_api_headers(guest_token)
        )
        assert response.status_code == 404
        assert OIDCBinding.objects.filter(pk=binding_id).exists()


@pytest.mark.django_db
class TestBindingCreateDefersForPrivateRepo:
    """A private repo can't be resolved unauthenticated, so the binding is
    created UNPINNED (IDs NULL) and the IDs are pinned later from the first
    OIDC token. Only a malformed slug is rejected outright (covered in
    TestBindingManagementCreate)."""

    def test_private_repo_creates_unpinned_binding(self, authenticated_api_client, owned_component, mocker) -> None:
        # resolve_repository 404s for a private repo (GitHubResolveError 'not_found').
        mocker.patch(
            "sbomify.apps.oidc.services.resolve_repository",
            side_effect=GitHubResolveError("not_found", "private or missing"),
        )
        client, token = authenticated_api_client

        response = client.post(
            BINDINGS_URL,
            data=json.dumps({"component_id": owned_component.id, "repository": "acme/private-repo"}),
            content_type="application/json",
            **get_api_headers(token),
        )

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["repository"] == "acme/private-repo"
        assert body["repository_id"] is None  # unpinned — awaiting first publish
        assert body["repository_owner_id"] is None
        binding = OIDCBinding.objects.get(pk=body["id"])
        assert binding.repository_id is None
        assert binding.bot_user is not None  # bot provisioned even while unpinned

    def test_transient_resolve_failure_also_defers(self, authenticated_api_client, owned_component, mocker) -> None:
        """A rate-limited / unreachable GitHub also defers (we can't read the IDs
        right now) — the binding is created unpinned rather than failing."""
        mocker.patch(
            "sbomify.apps.oidc.services.resolve_repository",
            side_effect=GitHubResolveError("unavailable", "github down"),
        )
        client, token = authenticated_api_client
        response = client.post(
            BINDINGS_URL,
            data=json.dumps({"component_id": owned_component.id, "repository": "acme/widget"}),
            content_type="application/json",
            **get_api_headers(token),
        )
        assert response.status_code == 201, response.content
        assert response.json()["repository_id"] is None

    def test_duplicate_unpinned_name_is_409(self, authenticated_api_client, owned_component, mocker) -> None:
        """Two UNPINNED bindings for the same name on a component conflict — the
        unpinned-name unique constraint maps to a 409."""
        mocker.patch(
            "sbomify.apps.oidc.services.resolve_repository",
            side_effect=GitHubResolveError("not_found", "private"),
        )
        client, token = authenticated_api_client
        body = json.dumps({"component_id": owned_component.id, "repository": "acme/private-repo"})

        first = client.post(BINDINGS_URL, data=body, content_type="application/json", **get_api_headers(token))
        assert first.status_code == 201
        second = client.post(BINDINGS_URL, data=body, content_type="application/json", **get_api_headers(token))
        assert second.status_code == 409, second.content

    def test_freed_name_rebindable_after_pin(self, authenticated_api_client, owned_component, mocker) -> None:
        """A PINNED binding keeps its (possibly stale-after-rename) name, but
        because pinned bindings are keyed by ID, that name must NOT block a new
        binding for the same name (e.g. a different repo that reused a freed
        name). Regression for the conditional uniqueness."""
        client, token = authenticated_api_client
        body = json.dumps({"component_id": owned_component.id, "repository": "acme/widget"})

        # 1) Public repo → resolved + pinned at create.
        mocker.patch(
            "sbomify.apps.oidc.services.resolve_repository",
            return_value=ResolvedRepository(
                repository="acme/widget", repository_owner="acme", repository_id=111, repository_owner_id=222
            ),
        )
        first = client.post(BINDINGS_URL, data=body, content_type="application/json", **get_api_headers(token))
        assert first.status_code == 201
        assert first.json()["repository_id"] == 111  # pinned

        # 2) New binding for the SAME name now defers (private) — not blocked by
        #    the pinned binding above (which is keyed by ID, not name).
        mocker.patch(
            "sbomify.apps.oidc.services.resolve_repository",
            side_effect=GitHubResolveError("not_found", "private"),
        )
        second = client.post(BINDINGS_URL, data=body, content_type="application/json", **get_api_headers(token))
        assert second.status_code == 201, second.content
        assert second.json()["repository_id"] is None  # unpinned


@pytest.mark.django_db
def test_partial_pin_rejected_by_check_constraint(component, sample_user) -> None:
    """The both-or-neither CheckConstraint forbids a half-pinned row (one ID
    set, the other NULL): it could never match an exchange and would fall into
    the wrong conditional-uniqueness branch."""
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            OIDCBinding.objects.create(
                component=component,
                provider=OIDCBinding.PROVIDER_GITHUB,
                repository="acme/widget",
                repository_id=12345,
                repository_owner_id=None,  # half-pinned → violates the constraint
                bot_user=None,
                created_by=sample_user,
            )


def _make_unpinned_binding(component: Component, repository: str, sample_user) -> OIDCBinding:
    """Create an UNPINNED binding (IDs NULL) with a provisioned bot user.

    Mirrors the real two-phase create in ``services.create_binding``: insert
    with ``bot_user=None`` (the FK is nullable for exactly this window), then
    provision the bot and attach it — no throwaway placeholder User needed.
    """
    binding = OIDCBinding.objects.create(
        component=component,
        provider=OIDCBinding.PROVIDER_GITHUB,
        repository=repository,
        repository_id=None,
        repository_owner_id=None,
        bot_user=None,
        created_by=sample_user,
    )
    bot = provision_bot_user_for_binding(binding)
    binding.bot_user = bot
    binding.save(update_fields=["bot_user"])
    return binding


@pytest.mark.django_db
class TestDeferredPinningAtExchange:
    """An unpinned binding gets its immutable IDs pinned from the first signed
    OIDC token (matched by repository name); afterwards it matches by ID."""

    def test_first_exchange_pins_ids(self, github_claims_factory, mock_github_jwks, component, sample_user) -> None:
        binding = _make_unpinned_binding(component, "acme/widget", sample_user)
        token = github_claims_factory(repository="acme/widget", repository_owner_id=67890, repository_id=12345)
        client = Client()

        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == 200, response.content
        binding.refresh_from_db()
        assert binding.repository_id == 12345  # pinned from the verified token
        assert binding.repository_owner_id == 67890

    def test_second_exchange_matches_by_pinned_id(
        self, github_claims_factory, mock_github_jwks, component, sample_user
    ) -> None:
        _make_unpinned_binding(component, "acme/widget", sample_user)
        token = github_claims_factory(repository="acme/widget", repository_owner_id=67890, repository_id=12345)
        client = Client()
        body = json.dumps({"component_id": component.id})
        headers = {"content_type": "application/json", "HTTP_AUTHORIZATION": f"Bearer {token}"}

        first = client.post(EXCHANGE_URL, data=body, **headers)
        second = client.post(EXCHANGE_URL, data=body, **headers)

        assert first.status_code == 200, first.content
        assert second.status_code == 200, second.content  # now matched on the pinned IDs

    def test_unpinned_binding_not_claimed_by_other_repo(
        self, github_claims_factory, mock_github_jwks, component, sample_user
    ) -> None:
        """A token for a DIFFERENT repo name must not pin/claim an unpinned
        binding — it stays unpinned and the exchange 403s."""
        binding = _make_unpinned_binding(component, "acme/widget", sample_user)
        token = github_claims_factory(repository="evil/forge", repository_owner_id=99999, repository_id=88888)
        client = Client()

        response = client.post(
            EXCHANGE_URL,
            data=json.dumps({"component_id": component.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == 403
        binding.refresh_from_db()
        assert binding.repository_id is None  # untouched
