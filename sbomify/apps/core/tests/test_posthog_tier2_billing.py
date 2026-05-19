"""Tier 2 PostHog tests for ``billing:*`` events."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.posthog_helpers import patch_capture
from sbomify.apps.teams.models import Team


@pytest.mark.django_db(transaction=True)
def test_handle_trial_period_emits_trial_expired_only_once(
    mocker: MockerFixture,
    team_with_business_plan: Team,
) -> None:
    """billing:trial_expired must fire exactly once per team, even on redelivered webhooks.

    Stripe can deliver multiple ``customer.subscription.updated`` events that
    still report ``status=trialing`` after we have already downgraded a team
    locally; we rely on a persistent marker in ``billing_plan_limits`` so the
    transition-only side effects do not run twice.

    Uses ``transaction=True`` because ``handle_trial_period`` defers the
    PostHog capture via ``transaction.on_commit`` and those callbacks only
    fire on a real commit (not on rollback at end of a non-transactional
    test).
    """
    import datetime
    from unittest.mock import MagicMock

    from django.utils import timezone

    from sbomify.apps.billing.billing_processing import handle_trial_period

    mock_capture = patch_capture(mocker)
    # The downgrade calls notify_team_owners → email_notifications.notify_trial_expired;
    # patch them out so the test does not depend on SMTP fixtures.
    mocker.patch("sbomify.apps.billing.billing_processing.email_notifications")
    mocker.patch("sbomify.apps.billing.billing_processing.handle_community_downgrade_visibility")

    subscription = MagicMock()
    subscription.status = "trialing"
    subscription.trial_end = int((timezone.now() - datetime.timedelta(days=1)).timestamp())

    assert handle_trial_period(subscription, team_with_business_plan) is True
    assert handle_trial_period(subscription, team_with_business_plan) is True

    trial_expired_calls = [c for c in mock_capture.call_args_list if c.args[1] == "billing:trial_expired"]
    assert len(trial_expired_calls) == 1, (
        f"Expected billing:trial_expired to fire exactly once, got {len(trial_expired_calls)} calls"
    )
