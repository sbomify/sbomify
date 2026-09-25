"""Stripe webhooks can arrive out of order; billing state follows the newest event.

Stripe does not deliver events in the order it created them, and it retries a
failed delivery for days. An event created before the newest one already applied
to a workspace describes a state that has since changed. The handlers ignore it,
except that they still record a payment it reports, and they always apply a
deletion, since Stripe never revives a deleted subscription.
"""

from __future__ import annotations

import pytest
import stripe

from sbomify.apps.billing import billing_processing, email_notifications
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_side_channels(mocker):
    mocker.patch("sbomify.apps.core.posthog_service.capture")
    mocker.patch("sbomify.apps.core.posthog_service.group_identify")
    client = mocker.patch("sbomify.apps.billing.billing_processing.stripe_client")
    client.get_subscription.return_value = _subscription("active")


@pytest.fixture(autouse=True)
def notify(mocker):
    return mocker.patch("sbomify.apps.billing.billing_processing.notify_billing_managers")


@pytest.fixture
def workspace(ensure_billing_plans, team_with_business_plan) -> Team:
    return team_with_business_plan


def _subscription(status: str, trial_end: int | None = None) -> stripe.Subscription:
    return stripe.Subscription.construct_from(
        {
            "id": "sub_test123",
            "object": "subscription",
            "customer": "cus_test123",
            "status": status,
            "cancel_at_period_end": False,
            "cancel_at": None,
            "trial_end": trial_end,
            "current_period_end": 1893456000,
            "metadata": {"plan_key": "business"},
            "items": {"object": "list", "data": [{"price": {"id": "price_test_business_monthly"}}]},
        },
        "sk_test_dummy",
    )


def _invoice() -> stripe.Invoice:
    return stripe.Invoice.construct_from(
        {
            "id": "in_test123",
            "object": "invoice",
            "subscription": "sub_test123",
            "amount_paid": 19900,
            "currency": "usd",
        },
        "sk_test_dummy",
    )


def _event(event_id: str, created: int) -> stripe.Event:
    return stripe.Event.construct_from({"id": event_id, "object": "event", "created": created}, "sk_test_dummy")


def test_an_update_older_than_the_cancellation_does_not_restore_the_paid_plan(workspace, notify):
    Team.objects.filter(pk=workspace.pk).update(billing_plan="community")
    billing_processing.handle_subscription_deleted(_subscription("canceled"), event=_event("evt_deleted", 200))
    notify.reset_mock()

    billing_processing.handle_subscription_updated(_subscription("active"), event=_event("evt_active", 100))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "canceled"
    assert workspace.billing_plan == "community"
    notify.assert_not_called()


def test_an_older_update_does_not_replace_a_newer_status(workspace):
    billing_processing.handle_subscription_updated(_subscription("past_due"), event=_event("evt_past_due", 200))
    billing_processing.handle_subscription_updated(_subscription("active"), event=_event("evt_active", 100))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "past_due"


def test_a_late_trial_notice_does_not_end_a_trial_that_became_paid(workspace, notify):
    billing_processing.handle_subscription_updated(_subscription("active"), event=_event("evt_paid", 300))
    notify.reset_mock()

    # trial_will_end is created three days before the trial ends and carries the trialing subscription.
    trialing = _subscription("trialing", trial_end=200)
    billing_processing.handle_subscription_updated(trialing, event=_event("evt_trial_will_end", 100))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "active"
    assert workspace.billing_plan == "business"
    notify.assert_not_called()


def test_an_older_payment_failure_does_not_undo_a_recovery(workspace, notify):
    billing_processing.handle_payment_succeeded(_invoice(), event=_event("evt_paid", 200))
    notify.reset_mock()

    billing_processing.handle_payment_failed(_invoice(), event=_event("evt_failed", 100))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "active"
    assert "payment_failed_at" not in workspace.billing_plan_limits
    notify.assert_not_called()


def test_an_older_payment_is_recorded_without_reactivating_a_canceled_subscription(workspace, notify):
    billing_processing.handle_subscription_deleted(_subscription("canceled"), event=_event("evt_deleted", 200))
    notify.reset_mock()

    billing_processing.handle_payment_succeeded(_invoice(), event=_event("evt_paid", 100))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "canceled"
    assert workspace.billing_plan_limits["last_payment_amount"] == 199.0
    notify.assert_called_once_with(workspace, email_notifications.notify_payment_succeeded)


def test_a_deletion_applies_after_an_event_created_later(workspace):
    billing_processing.handle_payment_succeeded(_invoice(), event=_event("evt_final_invoice", 201))
    billing_processing.handle_subscription_deleted(_subscription("canceled"), event=_event("evt_deleted", 200))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "canceled"


def test_a_late_deletion_does_not_make_older_events_look_new(workspace):
    billing_processing.handle_payment_succeeded(_invoice(), event=_event("evt_final_invoice", 201))
    billing_processing.handle_subscription_deleted(_subscription("canceled"), event=_event("evt_deleted", 199))
    billing_processing.handle_payment_failed(_invoice(), event=_event("evt_failed", 200))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "canceled"


def test_events_created_in_the_same_second_apply_in_arrival_order(workspace):
    billing_processing.handle_subscription_updated(_subscription("incomplete"), event=_event("evt_first", 100))
    billing_processing.handle_subscription_updated(_subscription("active"), event=_event("evt_second", 100))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "active"


def test_the_order_is_checked_against_the_locked_row(workspace, mocker):
    billing_processing.handle_subscription_updated(_subscription("past_due"), event=_event("evt_past_due", 200))
    # What the handler read before taking the lock, from before the newer event landed.
    mocker.patch.object(billing_processing, "_resolve_team_from_subscription", return_value=(workspace, {}))

    billing_processing.handle_subscription_updated(_subscription("active"), event=_event("evt_active", 100))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "past_due"


def test_a_recovery_update_ends_the_grace_period_when_its_payment_event_arrives_late(workspace):
    billing_processing.handle_payment_failed(_invoice(), event=_event("evt_failed", 50))
    billing_processing.handle_subscription_updated(_subscription("active"), event=_event("evt_active", 101))
    billing_processing.handle_payment_succeeded(_invoice(), event=_event("evt_paid", 100))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "active"
    assert "payment_failed_at" not in workspace.billing_plan_limits


def test_a_past_due_update_starts_the_grace_period_when_its_payment_event_arrives_late(workspace):
    billing_processing.handle_subscription_updated(_subscription("past_due"), event=_event("evt_past_due", 101))
    billing_processing.handle_payment_failed(_invoice(), event=_event("evt_failed", 100))

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits["subscription_status"] == "past_due"
    assert workspace.billing_plan_limits["payment_failed_at"]


def test_a_redelivery_caught_under_the_lock_sends_nothing(workspace, notify, mocker):
    billing_processing.handle_subscription_updated(_subscription("past_due"), event=_event("evt_past_due", 200))
    notify.reset_mock()
    # A concurrent delivery of the same event read the row before the first one committed.
    mocker.patch.object(billing_processing, "_resolve_team_from_subscription", return_value=(workspace, {}))

    billing_processing.handle_subscription_updated(_subscription("past_due"), event=_event("evt_past_due", 200))

    notify.assert_not_called()


def test_notifications_follow_the_status_read_under_the_lock(workspace, notify, mocker):
    billing_processing.handle_subscription_updated(_subscription("past_due"), event=_event("evt_past_due", 100))
    notify.reset_mock()
    # What the handler read before taking the lock, from before the past-due event landed.
    stale = {"subscription_status": "active"}
    mocker.patch.object(billing_processing, "_resolve_team_from_subscription", return_value=(workspace, stale))

    billing_processing.handle_subscription_updated(_subscription("active"), event=_event("evt_active", 200))

    notify.assert_called_once_with(workspace, email_notifications.notify_payment_succeeded)
