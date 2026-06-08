from unittest.mock import MagicMock

import pytest
import stripe

from sbomify.apps.billing.billing_processing import handle_subscription_updated
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.teams.models import Team


def _real_subscription(**overrides):
    """Build a genuine Stripe ``Subscription`` object (not a MagicMock).

    Real StripeObjects subclass dict, so ``.items`` resolves to the dict METHOD
    (shadowing the subscription's line items) — exactly the production condition
    that a MagicMock silently hides.
    """
    data = {
        "id": "sub_test_123",
        "object": "subscription",
        "customer": "cus_test_123",
        "status": "active",
        "cancel_at_period_end": False,
        "cancel_at": None,
        "current_period_end": 1893456000,
        "metadata": {"plan_key": "enterprise"},
        "items": {"object": "list", "data": [{"price": {"id": "price_test_enterprise"}}]},
    }
    data.update(overrides)
    return stripe.Subscription.construct_from(data, "sk_test_dummy")


@pytest.fixture
def enterprise_plan_with_price():
    plan, _ = BillingPlan.objects.get_or_create(key="enterprise", defaults={"name": "Enterprise"})
    plan.stripe_price_monthly_id = "price_test_enterprise"
    plan.save()
    return plan

@pytest.fixture
def team_with_subscription(db):
    team = Team.objects.create(
        key="test_team", 
        name="Test Team",
        billing_plan="business",
        billing_plan_limits={
            "stripe_subscription_id": "sub_test_123",
            "stripe_customer_id": "cus_test_123",
            "cancel_at_period_end": False
        }
    )
    return team

@pytest.mark.django_db
def test_handle_subscription_updated_price_id_match(enterprise_plan_with_price, team_with_subscription):
    """Test that subscription update with matching Price ID updates the team plan."""
    
    # Mock Subscription object
    mock_sub = MagicMock()
    mock_sub.id = "sub_test_123"
    mock_sub.customer = "cus_test_123"
    mock_sub.status = "active"
    mock_sub.current_period_end = 1770336664
    mock_sub.metadata = {}
    mock_sub.cancel_at_period_end = False    
    
    # Mock Item with Price ID
    mock_item = MagicMock()
    mock_item.price.id = "price_test_enterprise"
    mock_sub.items.data = [mock_item]
    
    # Execute
    handle_subscription_updated(mock_sub)
    
    # Verify
    team_with_subscription.refresh_from_db()
    assert team_with_subscription.billing_plan == "enterprise"
    assert team_with_subscription.billing_plan_limits["max_products"] == enterprise_plan_with_price.max_products

@pytest.mark.django_db
def test_handle_subscription_updated_cancel_at_period_end_sync(enterprise_plan_with_price, team_with_subscription):
    """Test that cancel_at_period_end flag is synced from subscription."""

    mock_sub = MagicMock()
    mock_sub.id = "sub_test_123"
    mock_sub.customer = "cus_test_123"
    mock_sub.status = "active"
    mock_sub.items.data = [MagicMock(price=MagicMock(id="price_test_enterprise"))]
    mock_sub.cancel_at_period_end = True

    handle_subscription_updated(mock_sub)

    team_with_subscription.refresh_from_db()
    assert team_with_subscription.billing_plan_limits["cancel_at_period_end"] is True


@pytest.mark.django_db
def test_handle_subscription_updated_missing_plan_raises_and_does_not_persist_active(team_with_subscription):
    """When the BillingPlan cannot be resolved, the event must retry — never persist stale 'active' limits.

    Reproduces #996: the handler logged ``critical`` but still saved
    ``subscription_status=active`` with stale plan limits. The fix raises a
    retryable error so the whole transaction rolls back and Stripe retries.
    """
    from sbomify.apps.billing.stripe_client import BillingRetryableError

    # Pre-seed STALE values so the rollback assertions below are meaningful rather
    # than tautological (the fixture otherwise lacks both keys).
    team_with_subscription.billing_plan_limits.update(
        {"subscription_status": "past_due", "last_processed_webhook_id": "evt_old"}
    )
    team_with_subscription.save()

    mock_sub = MagicMock()
    mock_sub.id = "sub_test_123"
    mock_sub.customer = "cus_test_123"
    mock_sub.status = "active"
    mock_sub.current_period_end = 1893456000
    mock_sub.cancel_at_period_end = False
    mock_sub.cancel_at = None
    # Price ID matches no plan, and the metadata fallback key does not exist either.
    mock_sub.metadata = {"plan_key": "does_not_exist"}
    mock_sub.items.data = [MagicMock(price=MagicMock(id="price_unmatched"))]

    with pytest.raises(BillingRetryableError):
        handle_subscription_updated(mock_sub)

    team_with_subscription.refresh_from_db()
    # Rollback: the stale values must be preserved, NOT overwritten with the
    # incoming 'active' status / new webhook id from the partially-applied update.
    assert team_with_subscription.billing_plan_limits["subscription_status"] == "past_due"
    assert team_with_subscription.billing_plan_limits["last_processed_webhook_id"] == "evt_old"


@pytest.mark.django_db
def test_subscription_updated_syncs_plan_from_items_on_real_stripe_object(
    enterprise_plan_with_price, team_with_subscription
):
    """Plan/limits must sync from the subscription's line items for REAL Stripe events.

    Guards against the ``StripeObject.items`` shadowing bug: ``getattr(sub, "items")``
    returns the dict method, so the line-item plan-resolution block was skipped for
    real webhook payloads (a MagicMock hid this because attribute access worked).
    """
    sub = _real_subscription()  # price_test_enterprise -> enterprise plan

    handle_subscription_updated(sub)

    team_with_subscription.refresh_from_db()
    assert team_with_subscription.billing_plan == "enterprise"
    assert team_with_subscription.billing_plan_limits["max_products"] == enterprise_plan_with_price.max_products


@pytest.mark.django_db
def test_subscription_updated_missing_plan_is_retryable_on_real_stripe_object(team_with_subscription):
    """The missing-plan retryable path must be reachable for REAL Stripe events too."""
    from sbomify.apps.billing.stripe_client import BillingRetryableError

    sub = _real_subscription(
        metadata={"plan_key": "does_not_exist"},
        items={"object": "list", "data": [{"price": {"id": "price_unmatchable"}}]},
    )

    with pytest.raises(BillingRetryableError):
        handle_subscription_updated(sub)
