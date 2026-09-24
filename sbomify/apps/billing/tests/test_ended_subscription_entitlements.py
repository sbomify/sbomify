"""A paid subscription that ends puts the workspace on Community.

Every path that learns a subscription has ended moves the workspace to Community
limits and publishes its components: the deleted webhook with or without a
scheduled cancel, an updated webhook carrying an ended status, the Stripe sync,
the missing-subscription reconcile and the stale-trial sweep. A payment that
recovers restores the paid plan. Enterprise workspaces are set by hand and keep
their plan.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.utils import timezone

from sbomify.apps.billing import billing_processing, stripe_sync
from sbomify.apps.billing.billing_helpers import downgrade_ended_subscription
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.sboms.models import Component, Product
from sbomify.apps.teams.models import Team

ENDED_STATUSES = ["canceled", "unpaid", "incomplete_expired", "paused"]

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_side_channels(mocker):
    mocker.patch("sbomify.apps.billing.billing_processing.notify_billing_managers")
    mocker.patch("sbomify.apps.billing.billing_processing.stripe_client")
    mocker.patch("sbomify.apps.core.posthog_service.capture")
    mocker.patch("sbomify.apps.core.posthog_service.group_identify")


@pytest.fixture
def paid_workspace(ensure_billing_plans, team_with_business_plan) -> Team:
    team = team_with_business_plan
    Component.objects.create(name="private-component", team=team, visibility=Component.Visibility.PRIVATE)
    return team


def _subscription(status: str, *, sub_id: str = "sub_test123", customer: str = "cus_test123") -> MagicMock:
    business = BillingPlan.objects.get(key="business")
    subscription = MagicMock()
    subscription.id = sub_id
    subscription.customer = customer
    subscription.status = status
    subscription.cancel_at_period_end = False
    subscription.cancel_at = None
    subscription.trial_end = None
    subscription.current_period_end = int(timezone.now().timestamp()) + 86400
    subscription.metadata = {"plan_key": "business"}
    subscription.items.data = [MagicMock(price=MagicMock(id=business.stripe_price_monthly_id))]
    return subscription


def _event(event_id: str) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    return event


def _assert_on_community(team: Team) -> None:
    team.refresh_from_db()
    community = BillingPlan.objects.get(key="community")
    assert team.billing_plan == "community"
    assert team.billing_plan_limits["max_products"] == community.max_products
    assert team.billing_plan_limits["max_components"] == community.max_components
    assert not team.can_be_private()
    assert not Component.objects.filter(team=team).exclude(visibility=Component.Visibility.PUBLIC).exists()


def test_deleted_subscription_without_a_scheduled_cancel_moves_to_community(paid_workspace):
    billing_processing.handle_subscription_deleted(_subscription("canceled"), event=_event("evt_deleted"))

    _assert_on_community(paid_workspace)
    assert paid_workspace.billing_plan_limits["subscription_status"] == "canceled"


def test_deleted_subscription_over_the_community_limits_still_moves_to_community(paid_workspace):
    community = BillingPlan.objects.get(key="community")
    for index in range(community.max_products + 1):
        Product.objects.create(name=f"product-{index}", team=paid_workspace)
    limits = paid_workspace.billing_plan_limits
    limits.update({"cancel_at_period_end": True, "scheduled_downgrade_plan": "community"})
    Team.objects.filter(pk=paid_workspace.pk).update(billing_plan_limits=limits)

    billing_processing.handle_subscription_deleted(_subscription("canceled"), event=_event("evt_deleted"))

    _assert_on_community(paid_workspace)
    assert paid_workspace.billing_plan_limits["downgrade_exceeded"] is True


@pytest.mark.parametrize("status", ENDED_STATUSES)
def test_updated_event_with_an_ended_status_moves_to_community(paid_workspace, status):
    billing_processing.handle_subscription_updated(_subscription(status), event=_event(f"evt_{status}"))

    _assert_on_community(paid_workspace)
    assert paid_workspace.billing_plan_limits["subscription_status"] == status


def test_payment_recovery_restores_the_paid_plan(paid_workspace):
    billing_processing.handle_subscription_updated(_subscription("unpaid"), event=_event("evt_unpaid"))
    billing_processing.handle_subscription_updated(_subscription("active"), event=_event("evt_active"))

    paid_workspace.refresh_from_db()
    business = BillingPlan.objects.get(key="business")
    assert paid_workspace.billing_plan == "business"
    assert paid_workspace.billing_plan_limits["max_products"] == business.max_products


def test_stripe_sync_of_an_ended_subscription_moves_to_community(paid_workspace):
    # A real StripeObject: the sync caches what it fetched, and a MagicMock does not pickle.
    canceled = stripe.Subscription.construct_from(
        {
            "id": "sub_test123",
            "customer": "cus_test123",
            "status": "canceled",
            "cancel_at_period_end": False,
            "cancel_at": None,
            "current_period_end": int(timezone.now().timestamp()),
            "items": {"data": [{"price": {"id": "price_x", "recurring": {"interval": "month"}}}]},
        },
        "sk_test",
    )
    with patch.object(stripe_sync.stripe_client, "get_subscription", return_value=canceled):
        assert stripe_sync.sync_subscription_from_stripe(paid_workspace, force_refresh=True)

    _assert_on_community(paid_workspace)


def test_reconciling_a_missing_subscription_moves_to_community(paid_workspace):
    assert stripe_sync.reconcile_missing_subscription(paid_workspace, "sub_test123")

    _assert_on_community(paid_workspace)


def test_stale_trial_sweep_moves_an_ended_trial_to_community(paid_workspace):
    from sbomify.apps.billing.tasks import check_stale_trials_task

    limits = paid_workspace.billing_plan_limits
    limits.update(
        {"is_trial": True, "subscription_status": "trialing", "trial_end": int(timezone.now().timestamp()) - 86400}
    )
    Team.objects.filter(pk=paid_workspace.pk).update(billing_plan_limits=limits)
    client: Any = MagicMock()
    client.get_subscription.return_value = _subscription("canceled")

    with (
        patch("sbomify.apps.billing.tasks.is_billing_enabled", return_value=True),
        patch("sbomify.apps.billing.stripe_client.StripeClient", return_value=client),
    ):
        check_stale_trials_task()

    _assert_on_community(paid_workspace)


def test_moving_to_community_clears_a_scheduled_cancel(paid_workspace):
    limits = paid_workspace.billing_plan_limits
    limits.update({"cancel_at_period_end": True, "scheduled_downgrade_plan": "community"})
    Team.objects.filter(pk=paid_workspace.pk).update(billing_plan_limits=limits)

    assert downgrade_ended_subscription(paid_workspace.pk)

    _assert_on_community(paid_workspace)
    assert "scheduled_downgrade_plan" not in paid_workspace.billing_plan_limits
    assert paid_workspace.billing_plan_limits["cancel_at_period_end"] is False


def test_enterprise_workspace_keeps_its_plan_when_a_subscription_ends(paid_workspace):
    Team.objects.filter(pk=paid_workspace.pk).update(billing_plan="enterprise")

    billing_processing.handle_subscription_deleted(_subscription("canceled"), event=_event("evt_deleted"))

    paid_workspace.refresh_from_db()
    assert paid_workspace.billing_plan == "enterprise"
    assert paid_workspace.billing_plan_limits["subscription_status"] == "canceled"
