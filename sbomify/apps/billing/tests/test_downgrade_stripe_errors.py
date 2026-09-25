"""Downgrading to Community through the API acts on what Stripe reports.

The downgrade read any Stripe failure as "this workspace has no subscription"
and switched it to Community on the spot, publishing its components while the
subscription kept billing. It now switches locally only when Stripe says the
subscription is gone or ended, and otherwise schedules the cancellation on the
subscription the workspace stored.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing.stripe_client import BillingRetryableError, StripeError, StripeResourceMissingError
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db


def _subscription(sub_id: str, status: str) -> MagicMock:
    subscription = MagicMock()
    subscription.id = sub_id
    subscription.status = status
    return subscription


def _stripe(*, subscription: MagicMock | None = None, listed: list | None = None, error: Exception | None = None):
    stripe = MagicMock()
    if error is not None:
        stripe.get_customer.side_effect = error
        stripe.get_subscription.side_effect = error
        stripe.list_subscriptions.side_effect = error
    else:
        stripe.get_customer.return_value = MagicMock(id="cus_test123")
        stripe.get_subscription.return_value = subscription
        stripe.list_subscriptions.return_value = MagicMock(data=listed if listed is not None else [subscription])
    return stripe


def _downgrade(team: Team, user, stripe: MagicMock):
    client = Client()
    client.force_login(user)
    with patch("sbomify.apps.billing.apis.get_stripe_client", return_value=stripe):
        return client.post(
            reverse("api-1:change_plan"),
            json.dumps({"plan": "community", "team_key": team.key}),
            content_type="application/json",
        )


@pytest.fixture
def private_component(team_with_business_plan):
    return Component.objects.create(name="app", team=team_with_business_plan, visibility=Component.Visibility.PRIVATE)


@pytest.fixture
def scheduled_downgrade(team_with_business_plan):
    team_with_business_plan.billing_plan_limits |= {
        "cancel_at_period_end": True,
        "scheduled_downgrade_plan": "community",
    }
    team_with_business_plan.save()


def test_a_transient_stripe_error_changes_nothing(
    ensure_billing_plans, team_with_business_plan, sample_user, private_component
):
    response = _downgrade(
        team_with_business_plan, sample_user, _stripe(error=BillingRetryableError("Could not connect"))
    )

    assert response.status_code == 503
    team_with_business_plan.refresh_from_db()
    private_component.refresh_from_db()
    assert team_with_business_plan.billing_plan == "business"
    assert private_component.visibility == Component.Visibility.PRIVATE


def test_any_other_stripe_error_changes_nothing(
    ensure_billing_plans, team_with_business_plan, sample_user, private_component
):
    response = _downgrade(team_with_business_plan, sample_user, _stripe(error=StripeError("Authentication failed")))

    assert response.status_code == 400
    team_with_business_plan.refresh_from_db()
    private_component.refresh_from_db()
    assert team_with_business_plan.billing_plan == "business"
    assert private_component.visibility == Component.Visibility.PRIVATE


def test_a_subscription_missing_at_stripe_downgrades_locally(
    ensure_billing_plans, team_with_business_plan, sample_user, private_component, scheduled_downgrade
):
    response = _downgrade(
        team_with_business_plan, sample_user, _stripe(error=StripeResourceMissingError("No such subscription"))
    )

    assert response.status_code == 200
    team_with_business_plan.refresh_from_db()
    private_component.refresh_from_db()
    assert team_with_business_plan.billing_plan == "community"
    assert private_component.visibility == Component.Visibility.PUBLIC
    limits = team_with_business_plan.billing_plan_limits
    assert "stripe_subscription_id" not in limits
    assert "stripe_customer_id" not in limits
    assert limits["subscription_status"] == "canceled"
    assert "scheduled_downgrade_plan" not in limits
    assert limits["cancel_at_period_end"] is False


@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
def test_an_ended_subscription_downgrades_locally(
    ensure_billing_plans, team_with_business_plan, sample_user, scheduled_downgrade, status
):
    stripe = _stripe(subscription=_subscription("sub_test123", status))

    response = _downgrade(team_with_business_plan, sample_user, stripe)

    assert response.status_code == 200
    stripe.modify_subscription.assert_not_called()
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan == "community"
    limits = team_with_business_plan.billing_plan_limits
    assert limits["subscription_status"] == status
    assert "scheduled_downgrade_plan" not in limits
    assert limits["cancel_at_period_end"] is False


def test_the_downgrade_cancels_the_stored_subscription(ensure_billing_plans, team_with_business_plan, sample_user):
    stored = _subscription("sub_test123", "active")
    stripe = _stripe(subscription=stored, listed=[_subscription("sub_other", "active"), stored])

    response = _downgrade(team_with_business_plan, sample_user, stripe)

    assert response.status_code == 200
    stripe.modify_subscription.assert_called_once_with("sub_test123", cancel_at_period_end=True)


def test_the_downgrade_keeps_the_status_stripe_reports(ensure_billing_plans, team_with_business_plan, sample_user):
    stripe = _stripe(subscription=_subscription("sub_test123", "trialing"))

    _downgrade(team_with_business_plan, sample_user, stripe)

    team_with_business_plan.refresh_from_db()
    limits = team_with_business_plan.billing_plan_limits
    assert limits["scheduled_downgrade_plan"] == "community"
    assert limits["subscription_status"] == "trialing"
