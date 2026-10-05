"""Invoices and subscriptions in both of Stripe's payload shapes.

API version 2025-03-31 moved an invoice's subscription to
``parent.subscription_details.subscription`` and a subscription's
``current_period_end`` onto its items. Our requests are pinned to a version
after that change, while webhook payloads follow the endpoint's own version,
so the handlers receive both shapes.

Events are signed and posted to the webhook URL, so Stripe's own
``construct_event`` builds the objects the handlers read.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import patch

import pytest
import stripe
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.billing.stripe_sync import get_period_end_from_subscription

pytestmark = pytest.mark.django_db

PERIOD_END = 1893456000  # 2030-01-01T00:00:00Z
PERIOD_END_ISO = datetime.datetime.fromtimestamp(PERIOD_END, tz=datetime.UTC).isoformat()


def _invoice(shape: str) -> dict[str, Any]:
    invoice: dict[str, Any] = {
        "id": "in_payload_shapes",
        "object": "invoice",
        "created": 1790000000,
        "amount_paid": 19900,
        "currency": "usd",
    }
    if shape == "subscription":
        invoice["subscription"] = "sub_test123"
    else:
        invoice["parent"] = {
            "type": "subscription_details",
            "quote_details": None,
            "subscription_details": {"metadata": {}, "subscription": "sub_test123"},
        }
    return invoice


def _subscription(*item_period_ends: int, **fields: Any) -> stripe.Subscription:
    """A subscription as the pinned version returns it: each item carries its own period."""
    items = [
        {
            "id": f"si_{n}",
            "object": "subscription_item",
            "current_period_end": period_end,
            "price": {
                "id": "price_test_business_monthly",
                "object": "price",
                "recurring": {"interval": "month", "interval_count": 1},
            },
        }
        for n, period_end in enumerate(item_period_ends)
    ]
    return stripe.Subscription.construct_from(
        {
            "id": "sub_test123",
            "object": "subscription",
            "customer": "cus_test123",
            "status": "active",
            "billing_cycle_anchor": 1769817600,
            "cancel_at": None,
            "cancel_at_period_end": False,
            "trial_end": None,
            "metadata": {"plan_key": "business"},
            "items": {"object": "list", "data": items},
            **fields,
        },
        "sk_test_payload_shapes",
    )


def _post_event(client: Any, event_type: str, obj: dict[str, Any]) -> Any:
    payload = json.dumps({"id": "evt_payload_shapes", "object": "event", "type": event_type, "data": {"object": obj}})
    timestamp = int(time.time())
    signed = f"{timestamp}.{payload}".encode()
    signature = hmac.new(settings.STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return client.post(
        reverse("billing:webhook"),
        data=payload,
        content_type="application/json",
        headers={"Stripe-Signature": f"t={timestamp},v1={signature}"},
    )


@pytest.mark.parametrize("shape", ["subscription", "parent"])
def test_failed_payment_marks_the_workspace_past_due(client, team_with_business_plan, shape):
    response = _post_event(client, "invoice.payment_failed", _invoice(shape))

    assert response.status_code == 200
    team_with_business_plan.refresh_from_db()
    limits = team_with_business_plan.billing_plan_limits
    assert limits["subscription_status"] == "past_due"
    assert limits["payment_failed_at"]


@pytest.mark.parametrize("shape", ["subscription", "parent"])
def test_paid_invoice_clears_the_failure_and_records_the_next_billing_date(client, team_with_business_plan, shape):
    team_with_business_plan.billing_plan_limits.update(
        {"subscription_status": "past_due", "payment_failed_at": timezone.now().isoformat()}
    )
    team_with_business_plan.save()

    with patch("sbomify.apps.billing.billing_processing.stripe_client") as stripe_client:
        stripe_client.get_subscription.return_value = _subscription(PERIOD_END)
        response = _post_event(client, "invoice.payment_succeeded", _invoice(shape))

    assert response.status_code == 200
    team_with_business_plan.refresh_from_db()
    limits = team_with_business_plan.billing_plan_limits
    assert limits["subscription_status"] == "active"
    assert "payment_failed_at" not in limits
    assert limits["next_billing_date"] == PERIOD_END_ISO


def test_checkout_records_the_next_billing_date(client, team_with_business_plan):
    session = {
        "id": "cs_payload_shapes",
        "object": "checkout.session",
        "payment_status": "paid",
        "customer": "cus_test123",
        "subscription": "sub_test123",
        "amount_total": 19900,
        "currency": "usd",
        "metadata": {"team_key": team_with_business_plan.key, "plan_key": "business"},
    }

    with patch("sbomify.apps.billing.billing_processing.stripe_client") as stripe_client:
        stripe_client.get_subscription.return_value = _subscription(PERIOD_END)
        response = _post_event(client, "checkout.session.completed", session)

    assert response.status_code == 200
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["next_billing_date"] == PERIOD_END_ISO


@pytest.mark.parametrize("event_type", ["invoice.payment_failed", "invoice.payment_succeeded"])
def test_invoice_without_a_subscription_changes_nothing(client, team_with_business_plan, event_type):
    limits_before = dict(team_with_business_plan.billing_plan_limits)
    one_off_invoice = {**_invoice("parent"), "parent": None}

    response = _post_event(client, event_type, one_off_invoice)

    assert response.status_code == 200
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits == limits_before


@pytest.mark.parametrize(
    ("subscription", "expected"),
    [
        pytest.param(_subscription(current_period_end=PERIOD_END), PERIOD_END_ISO, id="top-level"),
        pytest.param(_subscription(PERIOD_END), PERIOD_END_ISO, id="item"),
        pytest.param(_subscription(PERIOD_END + 86400, PERIOD_END), PERIOD_END_ISO, id="earliest-item"),
    ],
)
def test_period_end_is_read_from_either_shape(subscription, expected):
    """Every settings render stores this as next_billing_date, so an estimate here overwrites the real date."""
    assert get_period_end_from_subscription(subscription, "sub_test123") == expected
