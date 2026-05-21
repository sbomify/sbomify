"""Idempotency guards for trial-expired processing.

Stripe redelivers ``customer.subscription.updated`` events freely and we
also re-poll trial status from other code paths, so any branch that
fires user-visible side effects (emails, visibility downgrades, PostHog
captures) must run exactly once per team per real expiry. The guard
implements a two-marker state machine that survives crashes and
concurrent webhooks alike.
"""

from __future__ import annotations

import datetime
from typing import Any

from django.conf import settings


class TrialExpiryEmissionGuard:
    """Two-marker state machine for exactly-once trial-expired side effects.

    Markers are stored in ``Team.billing_plan_limits``:

    * ``trial_expired_claimed_at`` — reserved under a row lock by the
      caller that wins the race. Acts as the gate: concurrent webhooks
      cannot both see "unclaimed" and both fire.
    * ``trial_expired_emitted_at`` — written only after every side
      effect has succeeded. If any side effect raises, the claim stays
      open without a completion marker, and a later webhook past
      ``stale_seconds`` can retake the claim and finish the work.

    The two-marker shape (vs. a single marker) is what makes the work
    crash-tolerant — a single "set marker before side effects" would
    permanently swallow side effects on a mid-run crash.

    Usage in the caller's downgrade flow (see
    ``handle_trial_period``)::

        guard = TrialExpiryEmissionGuard()
        with transaction.atomic():
            team = Team.objects.select_for_update().get(pk=team.pk)
            billing_limits = (team.billing_plan_limits or {}).copy()
            now = timezone.now()
            should_run = guard.should_claim(billing_limits, now)
            # ... other write fields ...
            if should_run:
                guard.stamp_claim(billing_limits, now)
            team.billing_plan_limits = billing_limits
            team.save()

        if should_run:
            # ... run side effects ...
            with transaction.atomic():
                team = Team.objects.select_for_update().get(pk=team.pk)
                billing_limits = (team.billing_plan_limits or {}).copy()
                guard.stamp_emitted(billing_limits, timezone.now())
                team.billing_plan_limits = billing_limits
                team.save()
                # defer the PostHog capture via transaction.on_commit
                # so the marker is durable BEFORE the event ships
    """

    CLAIMED_MARKER = "trial_expired_claimed_at"
    EMITTED_MARKER = "trial_expired_emitted_at"
    DEFAULT_STALE_SECONDS = 600

    def __init__(self, stale_seconds: int | None = None) -> None:
        if stale_seconds is None:
            stale_seconds = getattr(settings, "TRIAL_EXPIRED_CLAIM_STALE_SECONDS", self.DEFAULT_STALE_SECONDS)
        self.stale_seconds: int = stale_seconds

    def should_claim(self, billing_limits: dict[str, Any], now: datetime.datetime) -> bool:
        """Decide whether this caller wins the side-effects slot.

        Returns ``True`` when side effects have not already completed AND
        no fresh claim exists. A corrupt or unparseable claim marker is
        treated as no claim (retake), since the alternative is a
        permanent stall on a single bad write.

        Also treats an aware/naive-datetime mismatch as a corrupt marker:
        if the persisted ``claimed_at`` is missing a timezone (e.g. an
        old write from before the codebase fully adopted aware
        timestamps) and ``now`` is aware, the subtraction raises
        ``TypeError`` — we treat that as a corrupt claim rather than
        propagating the error, so a single bad write can't deadlock the
        guard for a team.
        """
        if billing_limits.get(self.EMITTED_MARKER):
            return False
        claimed_at = billing_limits.get(self.CLAIMED_MARKER)
        if not claimed_at:
            return True
        try:
            claim_dt = datetime.datetime.fromisoformat(claimed_at)
        except (TypeError, ValueError):
            return True
        try:
            elapsed = (now - claim_dt).total_seconds()
        except TypeError:
            # Aware/naive mismatch — treat as corrupt and let a fresh
            # claim overwrite it.
            return True
        return elapsed >= self.stale_seconds

    def stamp_claim(self, billing_limits: dict[str, Any], now: datetime.datetime) -> None:
        """Mutate ``billing_limits`` in place to record this caller's claim."""
        billing_limits[self.CLAIMED_MARKER] = now.isoformat()

    def stamp_emitted(self, billing_limits: dict[str, Any], now: datetime.datetime) -> None:
        """Mutate ``billing_limits`` in place to record completion."""
        billing_limits[self.EMITTED_MARKER] = now.isoformat()
