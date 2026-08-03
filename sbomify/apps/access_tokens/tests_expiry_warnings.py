"""Token expiry warnings: the bell provider and the daily email sweep."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone

from sbomify.apps.access_tokens.models import AccessToken, TokenExpiryWarning
from sbomify.apps.access_tokens.notifications import get_notifications
from sbomify.apps.access_tokens.tasks import warn_expiring_tokens
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def _bot_member(user: Any, team: Any) -> Member:
    member = Member(user=user, team=team, role="bot", is_default_team=False)
    member._is_oidc_bot_provisioning = True  # type: ignore[attr-defined]  # the OIDC provisioning escape hatch
    member.save()
    return member


def _token(user: Any, team: Any = None, days: int = 10, description: str = "ci token") -> AccessToken:
    return AccessToken.objects.create(
        user=user,
        team=team,
        description=description,
        encoded_token=f"tok-{description}-{days}-{user.pk}",
        expires_at=timezone.now() + timedelta(days=days),
    )


class TestBellProvider:
    def _request(self, rf: Any, user: Any, team: Any = None, role: str = "owner") -> Any:
        request = rf.get("/")
        request.user = user
        request.session = {}
        if team is not None:
            request.session["current_team"] = {"key": team.key, "role": role}
        return request

    def test_own_expiring_token_warns(self, rf: Any, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=5)

        notifications = get_notifications(self._request(rf, member.user, member.team))

        assert len(notifications) == 1
        assert "expires in 5 days" in notifications[0].message
        assert notifications[0].severity == "warning"
        assert (notifications[0].action_url or "").endswith("#tokens")

    def test_a_token_outside_the_window_stays_quiet(self, rf: Any, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=60)
        AccessToken.objects.create(
            user=member.user, team=member.team, description="forever", encoded_token="tok-forever"
        )

        assert get_notifications(self._request(rf, member.user, member.team)) == []

    def test_last_day_reads_as_error(self, rf: Any, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=1)

        notifications = get_notifications(self._request(rf, member.user, member.team))

        assert notifications[0].severity == "error"
        assert "tomorrow" in notifications[0].message

    def test_owner_sees_the_workspace_bots_token(
        self, rf: Any, sample_team_with_owner_member: Any, guest_user: Any
    ) -> None:
        member = sample_team_with_owner_member
        _bot_member(guest_user, member.team)
        _token(guest_user, member.team, days=3, description="oidc bot")

        notifications = get_notifications(self._request(rf, member.user, member.team))

        assert len(notifications) == 1
        assert "oidc bot" in notifications[0].message

    def test_guest_role_does_not_see_bot_tokens(
        self, rf: Any, sample_team_with_owner_member: Any, guest_user: Any
    ) -> None:
        member = sample_team_with_owner_member
        _bot_member(guest_user, member.team)
        _token(guest_user, member.team, days=3)

        assert get_notifications(self._request(rf, member.user, member.team, role="guest")) == []


class TestEmailSweep:
    def test_first_run_sends_the_tightest_threshold_only(self, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        token = _token(member.user, member.team, days=5)

        sent = warn_expiring_tokens.fn()

        assert sent == 1
        assert len(mail.outbox) == 1
        assert '"ci token"' in mail.outbox[0].subject
        assert mail.outbox[0].to == [member.user.email]
        # The 7-day warning went out; 14 is marked too so it cannot trail in.
        assert {w.threshold_days for w in token.expiry_warnings.all()} == {14, 7}

    def test_the_sweep_is_idempotent(self, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=5)

        warn_expiring_tokens.fn()
        assert warn_expiring_tokens.fn() == 0
        assert len(mail.outbox) == 1

    def test_crossing_the_next_threshold_warns_again(self, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        token = _token(member.user, member.team, days=10)

        warn_expiring_tokens.fn()  # 14-day warning
        token.expires_at = timezone.now() + timedelta(hours=12)
        token.save(update_fields=["expires_at"])
        sent = warn_expiring_tokens.fn()

        assert sent == 1
        assert len(mail.outbox) == 2
        assert {w.threshold_days for w in token.expiry_warnings.all()} == {14, 7, 1}

    def test_bot_token_mails_the_workspace_owners(self, sample_team_with_owner_member: Any, guest_user: Any) -> None:
        member = sample_team_with_owner_member
        _bot_member(guest_user, member.team)
        _token(guest_user, member.team, days=2, description="release bot")

        warn_expiring_tokens.fn()

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [member.user.email]

    def test_expired_and_eternal_tokens_are_ignored(self, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=-1, description="already gone")
        AccessToken.objects.create(
            user=member.user, team=member.team, description="forever", encoded_token="tok-eternal"
        )

        assert warn_expiring_tokens.fn() == 0
        assert TokenExpiryWarning.objects.count() == 0
