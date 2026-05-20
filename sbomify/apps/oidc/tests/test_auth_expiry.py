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
    def test_token_at_exact_expiry_rejected(self) -> None:
        """Boundary: ``is_expired`` uses ``now >= expires_at``, so an
        exact-tick match should reject (no fence-post off-by-one).
        """
        User = get_user_model()
        user = User.objects.create_user(username="oidc-user-3", password="x")
        # Lock the comparison time so we test the inclusive-vs-exclusive boundary
        now = timezone.now()
        encoded, _ = _make_token_for(user, expires_at=now)

        # Mock timezone.now to return EXACTLY the same instant
        import sbomify.apps.access_tokens.models as models_mod

        original_now = models_mod.timezone.now
        models_mod.timezone.now = lambda: now
        try:
            resolved_user, _ = get_user_and_token_record(encoded)
            assert resolved_user is None, "Token AT expires_at should be rejected (>= comparison)"
        finally:
            models_mod.timezone.now = original_now

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
