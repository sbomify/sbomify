"""Billing integrity: community-downgrade cancels the real subscription, grace period is
enforced and not reset on repeated failures."""

import datetime
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden
from django.utils import timezone

from sbomify.apps.billing import billing_processing
from sbomify.apps.billing.apis import _handle_community_downgrade
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.teams.models import Member, Team

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_community_downgrade_uses_stored_customer_id():
    """Downgrade must use the stored Stripe customer id (web checkout creates a random cus_),
    not f'c_{team.key}', so the active subscription is actually canceled instead of the plan
    being downgraded locally while billing continues."""
    BillingPlan.objects.create(key="business", name="Business")
    team = Team.objects.create(
        name="T",
        key="wsdowngrade",
        billing_plan="business",
        billing_plan_limits={
            "subscription_status": "active",
            "stripe_customer_id": "cus_random123",
            "stripe_subscription_id": "sub_abc",
        },
    )
    stripe = MagicMock()
    stripe.get_customer.return_value = MagicMock(id="cus_random123")
    stripe.list_subscriptions.return_value = MagicMock(data=[MagicMock(id="sub_abc")])

    status, _body = _handle_community_downgrade(team, stripe)

    assert status == 200
    stripe.get_customer.assert_called_once_with("cus_random123")  # not c_wsdowngrade
    stripe.modify_subscription.assert_called_once_with("sub_abc", cancel_at_period_end=True)


def test_payment_failed_does_not_reset_failure_time():
    """Repeated failed-payment events keep the FIRST payment_failed_at so the grace window
    can actually expire."""
    BillingPlan.objects.create(key="business", name="Business", max_products=10)
    original = (timezone.now() - datetime.timedelta(days=2)).isoformat()
    team = Team.objects.create(
        name="T",
        key="test-team-reset",
        billing_plan="business",
        billing_plan_limits={
            "subscription_status": "active",
            "stripe_subscription_id": "sub_reset",
            "stripe_customer_id": "cus_reset",
            "payment_failed_at": original,
        },
    )

    invoice = MagicMock()
    invoice.subscription = "sub_reset"
    invoice.id = "in_reset_1"
    with patch("sbomify.apps.billing.billing_processing.email_notifications"):
        billing_processing.handle_payment_failed(invoice)

    team.refresh_from_db()
    assert team.billing_plan_limits["subscription_status"] == "past_due"
    assert team.billing_plan_limits["payment_failed_at"] == original  # not reset to now


def test_past_due_without_failed_at_is_enforced():
    """A past_due subscription with no payment_failed_at must not escape enforcement: it is
    backfilled so the grace window starts and eventually blocks."""
    BillingPlan.objects.create(key="business", name="Business", max_products=10)
    team = Team.objects.create(
        name="T",
        key="test-team-nofail",
        billing_plan="business",
        billing_plan_limits={"subscription_status": "past_due"},  # no payment_failed_at
    )
    user = User.objects.create_user(username="nofail_user", email="nofail@example.com")
    Member.objects.create(team=team, user=user, role="owner")

    request = MagicMock()
    request.method = "POST"
    request.session = {"current_team": {"key": "test-team-nofail"}}
    request.headers = {}
    request.META = {}

    @billing_processing.check_billing_limits("product")
    def view(request):
        return "success"

    # First call backfills payment_failed_at to now -> within grace -> allowed, and persisted.
    assert view(request) == "success"
    team.refresh_from_db()
    assert "payment_failed_at" in team.billing_plan_limits

    # Age the backfilled stamp past the grace window -> blocked (no longer bypassed).
    team.billing_plan_limits["payment_failed_at"] = (timezone.now() - datetime.timedelta(days=4)).isoformat()
    team.save()
    result = view(request)
    assert isinstance(result, HttpResponseForbidden)
    assert "Grace period expired" in result.content.decode()


def test_payment_recovery_clears_failure_marker_so_grace_resets():
    """A recovered payment clears payment_failed_at, so a LATER failure starts a fresh grace
    window instead of reusing the old (already-expired) timestamp."""
    BillingPlan.objects.create(key="business", name="Business", max_products=10)
    old_failure = (timezone.now() - datetime.timedelta(days=10)).isoformat()  # long past grace
    team = Team.objects.create(
        name="T",
        key="test-team-recover",
        billing_plan="business",
        billing_plan_limits={
            "subscription_status": "past_due",
            "stripe_subscription_id": "sub_rec",
            "stripe_customer_id": "cus_rec",
            "payment_failed_at": old_failure,
        },
    )

    paid = MagicMock()
    paid.subscription = "sub_rec"
    paid.id = "in_paid_1"
    paid.amount_paid = 1000
    paid.currency = "usd"
    with patch("sbomify.apps.billing.billing_processing.email_notifications"):
        billing_processing.handle_payment_succeeded(paid)

    team.refresh_from_db()
    assert team.billing_plan_limits["subscription_status"] == "active"
    assert "payment_failed_at" not in team.billing_plan_limits  # cleared on recovery

    # A new failure now stamps a FRESH timestamp (not the old expired one).
    failed = MagicMock()
    failed.subscription = "sub_rec"
    failed.id = "in_fail_2"
    with patch("sbomify.apps.billing.billing_processing.email_notifications"):
        billing_processing.handle_payment_failed(failed)

    team.refresh_from_db()
    new_failure = datetime.datetime.fromisoformat(team.billing_plan_limits["payment_failed_at"])
    assert (timezone.now() - new_failure).total_seconds() < 10  # fresh, grace window restarts
