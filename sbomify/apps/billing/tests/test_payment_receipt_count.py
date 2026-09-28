"""One payment sends one "Payment received" email, whichever order Stripe delivers its events in."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import stripe

from sbomify.apps.billing import billing_processing, email_notifications

pytestmark = pytest.mark.django_db

T0 = 1_600_000_000


def _subscription(**fields: Any) -> stripe.Subscription:
    return stripe.Subscription.construct_from(
        {
            "id": "sub_test123",
            "object": "subscription",
            "customer": "cus_test123",
            "status": "active",
            "cancel_at": None,
            "cancel_at_period_end": False,
            "trial_end": None,
            "metadata": {"plan_key": "business"},
            "items": {"object": "list", "data": [{"id": "si_1", "price": {"id": "price_unknown"}}]},
            **fields,
        },
        "sk_test_receipts",
    )


def _invoice(created: int) -> SimpleNamespace:
    return SimpleNamespace(
        id="in_first", created=created, amount_paid=19900, currency="usd", subscription="sub_test123", parent=None
    )


def _update(status: str, created: int, **fields: Any) -> None:
    billing_processing.handle_subscription_updated(
        _subscription(status=status, **fields), SimpleNamespace(id=f"evt_update_{created}", created=created)
    )


def _payment(created: int) -> None:
    billing_processing.handle_payment_succeeded(
        _invoice(created), SimpleNamespace(id=f"evt_paid_{created}", created=created)
    )


def _receipts(notify) -> int:
    return sum(
        1
        for call in notify.call_args_list
        if (call.args[1] if len(call.args) > 1 else call.kwargs.get("notification_fn"))
        is email_notifications.notify_payment_succeeded
    )


@pytest.fixture
def notify():
    with (
        patch("sbomify.apps.billing.billing_processing.notify_billing_managers") as notify,
        patch("sbomify.apps.billing.billing_processing.stripe_client") as client,
    ):
        client.get_subscription.return_value = _subscription()
        yield notify


@pytest.fixture
def team(team_with_business_plan):
    team_with_business_plan.billing_plan_limits = {
        **team_with_business_plan.billing_plan_limits,
        "stripe_subscription_id": "sub_test123",
        "stripe_customer_id": "cus_test123",
        "subscription_status": "trialing",
    }
    team_with_business_plan.save()
    return team_with_business_plan


@pytest.mark.parametrize("payment_first", [True, False], ids=["payment_first", "update_first"])
def test_trial_that_expired_here_then_converted(notify, team, payment_first):
    _update("trialing", T0, trial_end=T0 - 3600)
    team.refresh_from_db()
    assert team.billing_plan_limits["subscription_status"] == "canceled"

    if payment_first:
        _payment(T0 + 3700)
        _update("active", T0 + 10)
    else:
        _update("active", T0 + 10)
        _payment(T0 + 3700)

    assert _receipts(notify) == 1


@pytest.mark.parametrize("payment_first", [True, False], ids=["payment_first", "update_first"])
def test_past_due_recovery(notify, team, payment_first):
    team.billing_plan_limits["subscription_status"] = "past_due"
    team.save()

    if payment_first:
        _payment(T0 + 1)
        _update("active", T0 + 2)
    else:
        _update("active", T0 + 1)
        _payment(T0 + 2)

    assert _receipts(notify) == 1
