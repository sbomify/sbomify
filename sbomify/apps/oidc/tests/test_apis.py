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
from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.oidc.services import provision_bot_user_for_binding
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team

EXCHANGE_URL = "/api/v1/auth/oidc/github/exchange"


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
    def test_wrong_audience_401(
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
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid OIDC token"

    @pytest.mark.django_db
    def test_expired_token_401(
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
        from django.core.cache import cache

        # Clear any existing rate-limit counters for the IP from prior tests.
        cache.clear()

        # Patch the rate limit to a small value so the test is fast.
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
    def test_jwks_unavailable_503(
        self, github_claims_factory, github_binding, component, mocker, rsa_keypair
    ) -> None:
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
