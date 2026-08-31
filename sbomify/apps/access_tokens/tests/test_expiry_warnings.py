"""Token expiry warnings: the bell provider and the daily email sweep."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives
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


def _token(
    user: Any, team: Any = None, days: int = 10, description: str = "ci token", lifetime: int = 90
) -> AccessToken:
    """A token with ``days`` left to run, issued for ``lifetime`` days total.

    ``created_at`` is ``auto_now_add``, so a token created in a test always
    starts out with its lifetime equal to its remaining time — the one shape
    where "issued short" and "issued long and since aged" are indistinguishable.
    The default backdates to 90 days, which is what a token sitting at 5 days
    remaining looks like in practice; the short-lived cases ask for a small
    ``lifetime`` explicitly.
    """
    token = AccessToken.objects.create(
        user=user,
        team=team,
        description=description,
        encoded_token=f"tok-{description}-{days}-{user.pk}",
        expires_at=timezone.now() + timedelta(days=days),
    )
    AccessToken.objects.filter(pk=token.pk).update(created_at=token.expires_at - timedelta(days=lifetime))
    token.refresh_from_db()
    return token


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

        # Demote the Member row, not just the session copy of it. The provider
        # reads the live row, so a session claiming "guest" over an owner row
        # would prove only that the cache can lie.
        member.role = "guest"
        member.save(update_fields=["role"])

        assert get_notifications(self._request(rf, member.user, member.team, role="guest")) == []

    def test_a_stale_session_role_does_not_unlock_bot_tokens(
        self, rf: Any, sample_team_with_owner_member: Any, guest_user: Any
    ) -> None:
        """The session role is a 300s cache and must not be the deciding source.

        A demoted admin keeps a session saying "owner" until it turns over; that
        window must not keep handing them the workspace's bot tokens.
        """
        member = sample_team_with_owner_member
        _bot_member(guest_user, member.team)
        _token(guest_user, member.team, days=3)

        member.role = "member"
        member.save(update_fields=["role"])

        assert get_notifications(self._request(rf, member.user, member.team, role="owner")) == []


class TestShortLivedTokensAreNotNagged:
    """A token made short-lived on purpose must not be reported as expiring.

    From staging, seconds after clicking "Add a 7-day token" in the CI/CD
    dialog:

        Access token "CI/CD setup (07 Aug 2026)" expires in 7 days. Just now

    The warning window is 14 days, so a 7-day token is inside it for its whole
    life: the bell fires at creation and never clears, and the daily sweep
    mails about a lifetime the reader chose a day earlier. The warning is for
    a long-lived token drifting toward expiry unnoticed, which this is not.
    """

    def _request(self, rf: Any, user: Any, team: Any) -> Any:
        request = rf.get("/")
        request.user = user
        request.session = {"current_team": {"key": team.key, "role": "owner"}}
        return request

    def test_a_freshly_minted_ci_token_does_not_warn(self, rf: Any, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=7, lifetime=7)

        assert get_notifications(self._request(rf, member.user, member.team)) == []

    def test_a_long_token_that_has_aged_into_the_window_still_warns(
        self, rf: Any, sample_team_with_owner_member: Any
    ) -> None:
        """The case the warning exists for: 5 days left of an original 90."""
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=5, lifetime=90)

        notifications = get_notifications(self._request(rf, member.user, member.team))

        assert len(notifications) == 1
        assert "expires in 5 days" in notifications[0].message

    def test_the_last_day_warns_even_for_a_short_token(self, rf: Any, sample_team_with_owner_member: Any) -> None:
        """Silence for the whole life would let a pipeline break unannounced."""
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=1, lifetime=7)

        notifications = get_notifications(self._request(rf, member.user, member.team))

        assert len(notifications) == 1
        assert notifications[0].severity == "error"

    def test_the_sweep_skips_a_threshold_already_true_at_creation(
        self, sample_team_with_owner_member: Any
    ) -> None:
        """A 7-day token is inside the 14- and 7-day thresholds the moment it
        exists, so neither says anything the reader did not just decide."""
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=7, lifetime=7)

        assert warn_expiring_tokens.fn() == 0
        assert mail.outbox == []

    def test_the_sweep_still_mails_that_token_on_its_final_day(self, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=1, lifetime=7)

        assert warn_expiring_tokens.fn() == 1
        assert "expires in 1 day" in mail.outbox[0].subject

    def test_a_threshold_equal_to_the_lifetime_is_skipped(self, sample_team_with_owner_member: Any) -> None:
        """The boundary the rule turns on: a token issued for exactly 14 days
        sits on the 14-day threshold the moment it exists, so it says nothing.
        """
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=14, lifetime=14)

        assert warn_expiring_tokens.fn() == 0
        assert mail.outbox == []

    def test_an_oidc_publish_token_never_reaches_the_bell(
        self, rf: Any, sample_team_with_owner_member: Any, guest_user: Any
    ) -> None:
        """From staging: the OIDC exchange mints a 15-minute token per CI
        publish, and each one sat on the owner's bell as "expires tomorrow"
        for its whole life, one badge per publish. A token born inside its
        final day has no final-day news to break.
        """
        member = sample_team_with_owner_member
        _bot_member(guest_user, member.team)
        for i in range(3):
            AccessToken.objects.create(
                user=guest_user,
                team=member.team,
                description="oidc:github:bind1234abcd",
                encoded_token=f"tok-oidc-{i}",
                expires_at=timezone.now() + timedelta(minutes=15),
            )

        assert get_notifications(self._request(rf, member.user, member.team)) == []

    def test_the_sweep_never_mails_about_a_publish_token(
        self, sample_team_with_owner_member: Any, guest_user: Any
    ) -> None:
        """The email side already agrees through its threshold arithmetic; pin
        the agreement so the two paths cannot drift apart at this boundary."""
        member = sample_team_with_owner_member
        _bot_member(guest_user, member.team)
        AccessToken.objects.create(
            user=guest_user,
            team=member.team,
            description="oidc:github:bind1234abcd",
            encoded_token="tok-oidc-sweep",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        assert warn_expiring_tokens.fn() == 0
        assert mail.outbox == []

    def test_the_tighter_thresholds_fire_once_it_has_aged(self, sample_team_with_owner_member: Any) -> None:
        """The same 14-day token a week on, expressed as a second fixture
        rather than by moving ``expires_at``: shifting it also moves the
        computed lifetime, and the sub-second remainder decides whether the
        ceiling lands on 7 or 8, which is a coin toss to hang a test on.
        """
        member = sample_team_with_owner_member
        token = _token(member.user, member.team, days=7, lifetime=14)

        assert warn_expiring_tokens.fn() == 1
        assert {w.threshold_days for w in token.expiry_warnings.all()} == {7}


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

    def test_no_reachable_recipient_does_not_burn_the_threshold(
        self, sample_team_with_owner_member: Any
    ) -> None:
        """A warning nobody could receive must not count as delivered.

        Marking the threshold anyway would let the token run to expiry in
        silence even once an address exists.
        """
        member = sample_team_with_owner_member
        member.user.email = ""
        member.user.save(update_fields=["email"])
        token = _token(member.user, member.team, days=5)

        assert warn_expiring_tokens.fn() == 0
        assert mail.outbox == []
        assert token.expiry_warnings.count() == 0

        # An address arrives before the token expires; the warning still goes out.
        member.user.email = "owner@example.com"
        member.user.save(update_fields=["email"])

        assert warn_expiring_tokens.fn() == 1
        assert [m.to for m in mail.outbox] == [["owner@example.com"]]

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

    def test_a_partly_delivered_warning_is_retried(
        self, sample_team_with_owner_member: Any, guest_user: Any, mocker: Any
    ) -> None:
        """One owner's address bouncing must not burn the threshold for the rest.

        A bot token warns every owner. If one send fails and the others succeed,
        marking the threshold would leave that owner unwarned until the token
        expired, so nothing is marked and the next sweep tries again.
        """
        member = sample_team_with_owner_member
        second = type(member.user).objects.create_user(
            username="owner2", email="owner2@example.com", password="password"
        )
        Member.objects.create(user=second, team=member.team, role="owner")
        _bot_member(guest_user, member.team)
        token = _token(guest_user, member.team, days=2, description="release bot")

        real_send = EmailMultiAlternatives.send

        def send_one_then_fail(self: Any, *args: Any, **kwargs: Any) -> Any:
            if self.to == ["owner2@example.com"]:
                raise OSError("mailbox unavailable")
            return real_send(self, *args, **kwargs)

        mocker.patch.object(EmailMultiAlternatives, "send", send_one_then_fail)

        warn_expiring_tokens.fn()

        assert token.expiry_warnings.count() == 0, "a partial delivery must not mark the threshold"

    def test_expired_and_eternal_tokens_are_ignored(self, sample_team_with_owner_member: Any) -> None:
        member = sample_team_with_owner_member
        _token(member.user, member.team, days=-1, description="already gone")
        AccessToken.objects.create(
            user=member.user, team=member.team, description="forever", encoded_token="tok-eternal"
        )

        assert warn_expiring_tokens.fn() == 0
        assert TokenExpiryWarning.objects.count() == 0
