"""Tests for the ``expires_at`` enforcement in ``get_user_and_token_record``.

These live in the OIDC test tree because OIDC is the consumer of the
``expires_at`` column. Lifecycle covered:

* PAT (``expires_at IS NULL``) — unaffected, still works forever
* OIDC token before TTL — accepted
* OIDC token past TTL — rejected, same shape as a missing/revoked row
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token, get_user_and_token_record


def _make_token_for(user: Any, *, expires_at: datetime.datetime | None) -> tuple[str, AccessToken]:
    encoded = create_personal_access_token(user)
    row = AccessToken.objects.create(
        encoded_token=encoded,
        description="test",
        user=user,
        expires_at=expires_at,
    )
    return encoded, row


class TestPersonalAccessTokensUnaffected:
    @pytest.mark.django_db
    def test_pat_with_null_expires_at_still_works(self) -> None:
        User = get_user_model()
        user = User.objects.create_user(username="pat-user", password="x")
        encoded, _ = _make_token_for(user, expires_at=None)

        resolved_user, row = get_user_and_token_record(encoded)
        assert resolved_user is not None
        assert resolved_user.pk == user.pk
        assert row is not None


class TestOIDCExpiry:
    @pytest.mark.django_db
    def test_token_before_ttl_accepted(self) -> None:
        User = get_user_model()
        user = User.objects.create_user(username="oidc-user-1", password="x")
        encoded, _ = _make_token_for(user, expires_at=timezone.now() + datetime.timedelta(seconds=300))

        resolved_user, row = get_user_and_token_record(encoded)
        assert resolved_user is not None
        assert row is not None

    @pytest.mark.django_db
    def test_token_past_ttl_rejected(self) -> None:
        """The whole point of OIDC-5 — once expires_at is in the past,
        the row is treated as if it didn't exist.
        """
        User = get_user_model()
        user = User.objects.create_user(username="oidc-user-2", password="x")
        encoded, _ = _make_token_for(user, expires_at=timezone.now() - datetime.timedelta(seconds=1))

        resolved_user, row = get_user_and_token_record(encoded)
        assert resolved_user is None
        assert row is None

    @pytest.mark.django_db
    def test_token_at_exact_expiry_rejected(self, mocker) -> None:
        """Boundary: ``is_expired`` uses ``now >= expires_at``, so an
        exact-tick match should reject (no fence-post off-by-one).

        Uses ``mocker.patch`` (not a try/finally monkey-patch) so the
        original ``timezone.now`` is restored even if the test is
        killed mid-execution. Safe under ``pytest-xdist``.
        """
        User = get_user_model()
        user = User.objects.create_user(username="oidc-user-3", password="x")
        # Lock the comparison time so we test the inclusive-vs-exclusive boundary
        now = timezone.now()
        encoded, _ = _make_token_for(user, expires_at=now)

        mocker.patch("sbomify.apps.access_tokens.models.timezone.now", return_value=now)
        resolved_user, _ = get_user_and_token_record(encoded)
        assert resolved_user is None, "Token AT expires_at should be rejected (>= comparison)"

    @pytest.mark.django_db
    def test_expired_token_in_full_auth_flow_returns_401(self, mocker: Any) -> None:
        """End-to-end through the Ninja auth middleware."""
        from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth

        User = get_user_model()
        user = User.objects.create_user(username="oidc-user-4", password="x")
        encoded, _ = _make_token_for(user, expires_at=timezone.now() - datetime.timedelta(minutes=5))

        fake_request = mocker.MagicMock()
        result = PersonalAccessTokenAuth().authenticate(fake_request, encoded)
        assert result is None


class TestUserLivenessGuard:
    """Regression for security finding C-1: ``get_user_and_token_record``
    must NOT accept tokens whose owner is ``is_active=False`` or has been
    soft-deleted (``deleted_at`` set). Matters most for OIDC bot users —
    revoking a bot must invalidate every in-flight token immediately, not
    at TTL expiry.
    """

    @pytest.mark.django_db
    def test_inactive_user_token_rejected(self) -> None:
        User = get_user_model()
        user = User.objects.create_user(username="inactive-user", password="x")
        encoded, _ = _make_token_for(user, expires_at=None)

        # Token works while user is active
        resolved, _ = get_user_and_token_record(encoded)
        assert resolved is not None

        # Deactivate → token immediately rejected
        user.is_active = False
        user.save(update_fields=["is_active"])
        resolved, row = get_user_and_token_record(encoded)
        assert resolved is None
        assert row is None

    @pytest.mark.django_db
    def test_soft_deleted_user_token_rejected(self) -> None:
        User = get_user_model()
        user = User.objects.create_user(username="soft-deleted-user", password="x")
        encoded, _ = _make_token_for(user, expires_at=None)

        # Token works before soft-delete
        resolved, _ = get_user_and_token_record(encoded)
        assert resolved is not None

        # Soft-delete → token immediately rejected
        user.deleted_at = timezone.now()
        user.save(update_fields=["deleted_at"])
        resolved, row = get_user_and_token_record(encoded)
        assert resolved is None
        assert row is None


class TestJWTLevelExpiry:
    """Regression for security finding C-3: OIDC-minted JWTs carry their
    own ``exp`` and ``aud`` claims. PyJWT enforces these at decode time
    — defense-in-depth on top of the DB ``expires_at`` column. Even if
    the DB row's ``expires_at`` is wiped by a tamper or migration bug,
    the JWT-level expiry still rejects the token.
    """

    @pytest.mark.django_db
    def test_oidc_jwt_carries_exp_aud_token_type(self) -> None:
        """Minted OIDC tokens include the defense-in-depth claims."""
        from django.conf import settings
        from jwt import decode as jwt_decode

        User = get_user_model()
        user = User.objects.create_user(username="oidc-claims-1", password="x")
        future = timezone.now() + datetime.timedelta(seconds=900)
        encoded = create_personal_access_token(
            user, expires_at=future.timestamp(), token_type="oidc"
        )

        payload = jwt_decode(
            encoded,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
        )
        assert payload["token_type"] == "oidc"
        assert payload["aud"] == settings.JWT_AUDIENCE
        assert "exp" in payload

    @pytest.mark.django_db
    def test_pat_jwt_has_no_exp_or_aud(self) -> None:
        """PATs stay long-lived: no ``exp`` / no ``aud`` claim. Revocation
        is DB-row only.
        """
        from django.conf import settings
        from jwt import decode as jwt_decode

        User = get_user_model()
        user = User.objects.create_user(username="pat-claims-1", password="x")
        encoded = create_personal_access_token(user)

        # Decode without audience or exp enforcement (since PAT has neither)
        payload = jwt_decode(
            encoded,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False, "verify_exp": False},
        )
        assert "exp" not in payload
        assert "aud" not in payload
        # token_type may be present (new) or absent (legacy) — both accepted
        assert payload.get("token_type", "pat") == "pat"

    @pytest.mark.django_db
    def test_oidc_jwt_past_exp_rejected_at_jwt_layer(self) -> None:
        """Even with the DB row's ``expires_at`` wiped, an expired OIDC
        JWT must NOT decode — the JWT-level ``exp`` is the second gate.
        """
        User = get_user_model()
        user = User.objects.create_user(username="oidc-jwt-expired", password="x")
        past = timezone.now() - datetime.timedelta(seconds=60)
        encoded = create_personal_access_token(
            user, expires_at=past.timestamp(), token_type="oidc"
        )

        # Create the DB row WITHOUT expires_at — simulating the DB-tamper
        # / migration-bug scenario the JWT-level gate guards against.
        AccessToken.objects.create(
            encoded_token=encoded,
            description="tamper sim",
            user=user,
            expires_at=None,  # tampered / wiped
        )

        resolved, row = get_user_and_token_record(encoded)
        assert resolved is None, "Expired JWT must reject even when DB expires_at is missing"
        assert row is None

    @pytest.mark.django_db
    def test_oidc_jwt_with_wrong_audience_rejected(self, mocker: Any) -> None:
        """Pinning ``aud`` defends against same-SECRET_KEY sibling services."""
        User = get_user_model()
        user = User.objects.create_user(username="oidc-wrong-aud", password="x")

        # Mint a JWT manually with the WRONG audience but otherwise valid
        from django.conf import settings
        from jwt import encode as jwt_encode

        future = timezone.now() + datetime.timedelta(seconds=300)
        bad_jwt = jwt_encode(
            {
                "iss": settings.JWT_ISSUER,
                "sub": str(user.pk),
                "salt": "abcd1234",
                "token_type": "oidc",
                "exp": int(future.timestamp()),
                "aud": "wrong-service",
            },
            settings.SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

        AccessToken.objects.create(
            encoded_token=bad_jwt,
            description="wrong aud",
            user=user,
            expires_at=future,
        )
        resolved, row = get_user_and_token_record(bad_jwt)
        assert resolved is None
        assert row is None
