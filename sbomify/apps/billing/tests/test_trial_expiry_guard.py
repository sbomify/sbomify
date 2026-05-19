"""Unit tests for ``TrialExpiryEmissionGuard`` — the two-marker state machine."""

from __future__ import annotations

import datetime

import pytest
from django.test import override_settings

from sbomify.apps.billing.trial_expiry import TrialExpiryEmissionGuard


def _now() -> datetime.datetime:
    return datetime.datetime(2026, 5, 19, 12, 0, 0, tzinfo=datetime.timezone.utc)


class TestShouldClaim:
    def test_empty_limits_returns_true(self) -> None:
        guard = TrialExpiryEmissionGuard()
        assert guard.should_claim({}, _now()) is True

    def test_emitted_marker_returns_false(self) -> None:
        guard = TrialExpiryEmissionGuard()
        limits = {guard.EMITTED_MARKER: _now().isoformat()}
        assert guard.should_claim(limits, _now()) is False

    def test_fresh_claim_returns_false(self) -> None:
        guard = TrialExpiryEmissionGuard(stale_seconds=600)
        now = _now()
        # Claim was 60 seconds ago — well inside the stale window
        recent = now - datetime.timedelta(seconds=60)
        limits = {guard.CLAIMED_MARKER: recent.isoformat()}
        assert guard.should_claim(limits, now) is False

    def test_stale_claim_returns_true(self) -> None:
        guard = TrialExpiryEmissionGuard(stale_seconds=600)
        now = _now()
        # Claim was 700 seconds ago — past the stale window, so retake
        stale = now - datetime.timedelta(seconds=700)
        limits = {guard.CLAIMED_MARKER: stale.isoformat()}
        assert guard.should_claim(limits, now) is True

    def test_corrupt_claim_returns_true(self) -> None:
        """A garbage claim marker must not lock the team out forever."""
        guard = TrialExpiryEmissionGuard()
        limits = {guard.CLAIMED_MARKER: "not-an-isoformat-string"}
        assert guard.should_claim(limits, _now()) is True

    def test_non_string_claim_returns_true(self) -> None:
        guard = TrialExpiryEmissionGuard()
        limits = {guard.CLAIMED_MARKER: 12345}
        assert guard.should_claim(limits, _now()) is True

    def test_naive_claim_against_aware_now_returns_true(self) -> None:
        """Aware/naive datetime mismatch is a corrupt claim, not a crash.

        A timestamp written before the codebase fully adopted aware
        datetimes could be missing tzinfo. ``now - naive_dt`` would
        raise TypeError; we treat that as a retake instead of letting
        the guard deadlock forever on a single bad row.
        """
        guard = TrialExpiryEmissionGuard()
        naive_iso = datetime.datetime(2026, 5, 19, 12, 0, 0).isoformat()  # no tzinfo
        limits = {guard.CLAIMED_MARKER: naive_iso}
        # _now() returns an aware datetime — subtraction would normally raise
        assert guard.should_claim(limits, _now()) is True

    def test_emitted_wins_over_fresh_claim(self) -> None:
        """If both markers are set, the emitted marker dominates — work is done."""
        guard = TrialExpiryEmissionGuard()
        now = _now()
        limits = {
            guard.CLAIMED_MARKER: (now - datetime.timedelta(seconds=10)).isoformat(),
            guard.EMITTED_MARKER: now.isoformat(),
        }
        assert guard.should_claim(limits, now) is False


class TestStampMethods:
    def test_stamp_claim_writes_iso_timestamp(self) -> None:
        guard = TrialExpiryEmissionGuard()
        limits: dict = {}
        now = _now()
        guard.stamp_claim(limits, now)
        assert limits[guard.CLAIMED_MARKER] == now.isoformat()

    def test_stamp_emitted_writes_iso_timestamp(self) -> None:
        guard = TrialExpiryEmissionGuard()
        limits: dict = {}
        now = _now()
        guard.stamp_emitted(limits, now)
        assert limits[guard.EMITTED_MARKER] == now.isoformat()

    def test_stamps_preserve_existing_keys(self) -> None:
        guard = TrialExpiryEmissionGuard()
        limits = {"unrelated": "value", "is_trial": False}
        guard.stamp_claim(limits, _now())
        guard.stamp_emitted(limits, _now())
        assert limits["unrelated"] == "value"
        assert limits["is_trial"] is False


class TestConfiguration:
    @override_settings(TRIAL_EXPIRED_CLAIM_STALE_SECONDS=42)
    def test_setting_overrides_default(self) -> None:
        guard = TrialExpiryEmissionGuard()
        assert guard.stale_seconds == 42

    def test_explicit_constructor_arg_overrides_setting(self) -> None:
        guard = TrialExpiryEmissionGuard(stale_seconds=999)
        assert guard.stale_seconds == 999

    def test_default_when_setting_missing(self) -> None:
        # Without override_settings, this hits the default fallback
        guard = TrialExpiryEmissionGuard()
        # Default is 600 unless settings.TRIAL_EXPIRED_CLAIM_STALE_SECONDS is set
        # in the test environment. Just assert it's a positive int.
        assert isinstance(guard.stale_seconds, int)
        assert guard.stale_seconds > 0


class TestRoundTrip:
    def test_full_lifecycle(self) -> None:
        """Simulate: first webhook claims, second is blocked, third sees emit and skips."""
        guard = TrialExpiryEmissionGuard(stale_seconds=600)
        limits: dict = {}
        now = _now()

        # First webhook arrives
        assert guard.should_claim(limits, now) is True
        guard.stamp_claim(limits, now)

        # Second webhook arrives 30s later, sees fresh claim → skip
        later = now + datetime.timedelta(seconds=30)
        assert guard.should_claim(limits, later) is False

        # First webhook finishes side effects, stamps completion
        guard.stamp_emitted(limits, later)

        # Third webhook arrives even later, sees emit → skip
        much_later = now + datetime.timedelta(hours=1)
        assert guard.should_claim(limits, much_later) is False

    def test_crash_recovery_after_claim_before_emit(self) -> None:
        """If the side-effect runner crashed, a stale claim must allow retake."""
        guard = TrialExpiryEmissionGuard(stale_seconds=600)
        now = _now()
        # First webhook claimed, then process died before stamp_emitted
        limits = {guard.CLAIMED_MARKER: now.isoformat()}

        # 700s later, recovery webhook arrives — past the stale window, retake
        recovery_time = now + datetime.timedelta(seconds=700)
        assert guard.should_claim(limits, recovery_time) is True


@pytest.mark.parametrize(
    "stale_seconds,age_seconds,expected",
    [
        (600, 0, False),  # just claimed
        (600, 599, False),  # one second under window
        (600, 600, True),  # exactly at window edge — retake
        (600, 601, True),  # past window
        (60, 30, False),
        (60, 90, True),
    ],
)
def test_stale_window_boundary(stale_seconds: int, age_seconds: int, expected: bool) -> None:
    """Verify the >= comparison at the stale-seconds boundary."""
    guard = TrialExpiryEmissionGuard(stale_seconds=stale_seconds)
    now = _now()
    claim_at = now - datetime.timedelta(seconds=age_seconds)
    limits = {guard.CLAIMED_MARKER: claim_at.isoformat()}
    assert guard.should_claim(limits, now) is expected
