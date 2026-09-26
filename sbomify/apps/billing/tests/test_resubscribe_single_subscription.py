"""A new checkout leaves the workspace with one live subscription.

Stripe's checkout webhook and the browser's return from checkout race. Only the
webhook cancelled the subscription a checkout replaced, and only when it landed
first, so the usual order left both subscriptions billing. The return now
cancels it too, events for a subscription the workspace has replaced leave the
workspace alone, and the plan API refuses to open a second subscription.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing import billing_processing
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db


def _set_limits(team: Team, **limits) -> None:
    current = team.billing_plan_limits or {}
    current.update(limits)
    Team.objects.filter(pk=team.pk).update(billing_plan_limits=current)
    team.refresh_from_db()


def _subscription(sub_id: str, status: str) -> MagicMock:
    subscription = MagicMock()
    subscription.id = sub_id
    subscription.status = status
    subscription.customer = "cus_test123"
    subscription.cancel_at = None
    subscription.cancel_at_period_end = False
    subscription.trial_end = None
    subscription.current_period_end = 1893456000
    subscription.metadata = {"plan_key": "business"}
    subscription.items.data = []
    return subscription


def _checkout_session(team: Team) -> MagicMock:
    session = MagicMock()
    session.id = "cs_new"
    session.payment_status = "paid"
    session.subscription = "sub_new"
    session.customer = "cus_test123"
    session.metadata = {"team_key": team.key, "plan_key": "business"}
    return session


@pytest.fixture
def stripe_client():
    """The shared StripeClient the views and webhook handlers both use, with Stripe replaced."""
    with (
        patch("sbomify.apps.billing.views.stripe_client") as views_client,
        patch("sbomify.apps.billing.billing_processing.stripe_client", views_client),
        patch("sbomify.apps.billing.views.sync_subscription_from_stripe"),
    ):
        views_client.get_customer.return_value = MagicMock(id="cus_test123")
        yield views_client


def _return_from_checkout(client: Client) -> None:
    client.get(reverse("billing:billing_return") + "?session_id=cs_new")


def test_return_from_checkout_cancels_the_subscription_it_replaces(stripe_client, team_with_business_plan, sample_user):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_old", subscription_status="past_due")
    stripe_client.get_checkout_session.return_value = _checkout_session(team_with_business_plan)
    subscriptions = {"sub_old": _subscription("sub_old", "past_due"), "sub_new": _subscription("sub_new", "active")}
    stripe_client.get_subscription.side_effect = lambda sub_id: subscriptions[sub_id]
    client = Client()
    client.force_login(sample_user)

    _return_from_checkout(client)

    stripe_client.cancel_subscription.assert_called_once_with("sub_old")
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_new"


def test_return_from_checkout_leaves_an_ended_subscription_alone(stripe_client, team_with_business_plan, sample_user):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_old", subscription_status="canceled")
    stripe_client.get_checkout_session.return_value = _checkout_session(team_with_business_plan)
    subscriptions = {"sub_old": _subscription("sub_old", "canceled"), "sub_new": _subscription("sub_new", "active")}
    stripe_client.get_subscription.side_effect = lambda sub_id: subscriptions[sub_id]
    client = Client()
    client.force_login(sample_user)

    _return_from_checkout(client)

    stripe_client.cancel_subscription.assert_not_called()
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_new"


def test_event_for_a_replaced_subscription_leaves_the_workspace_alone(stripe_client, team_with_business_plan):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_new", subscription_status="active")
    event = MagicMock()
    event.id = "evt_old_canceled"

    billing_processing.handle_subscription_updated(_subscription("sub_old", "canceled"), event=event)

    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_new"
    assert team_with_business_plan.billing_plan_limits["subscription_status"] == "active"


def test_event_for_the_replacement_applies_when_the_stored_subscription_ended(stripe_client, team_with_business_plan):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_old", subscription_status="canceled")
    event = MagicMock()
    event.id = "evt_new_active"

    billing_processing.handle_subscription_updated(_subscription("sub_new", "active"), event=event)

    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_new"
    assert team_with_business_plan.billing_plan_limits["subscription_status"] == "active"


def _change_plan(client: Client, team: Team):
    return client.post(
        reverse("api-1:change_plan"),
        json.dumps({"plan": "business", "billing_period": "monthly", "team_key": team.key}),
        content_type="application/json",
    )


def test_plan_api_refuses_a_second_subscription(team_with_business_plan, sample_user):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_live", subscription_status="active")
    client = Client()
    client.force_login(sample_user)
    stripe = MagicMock()

    with patch("sbomify.apps.billing.apis.get_stripe_client", return_value=stripe):
        response = _change_plan(client, team_with_business_plan)

    assert response.status_code == 409
    stripe.create_checkout_session.assert_not_called()


def test_plan_api_checks_out_on_the_stored_customer(team_with_business_plan, sample_user):
    _set_limits(
        team_with_business_plan,
        stripe_customer_id="cus_stored",
        stripe_subscription_id="sub_ended",
        subscription_status="canceled",
    )
    client = Client()
    client.force_login(sample_user)
    stripe = MagicMock()
    stripe.create_checkout_session.return_value = MagicMock(url="https://checkout.example.com/session")

    with patch("sbomify.apps.billing.apis.get_stripe_client", return_value=stripe):
        response = _change_plan(client, team_with_business_plan)

    assert response.status_code == 200
    assert stripe.create_checkout_session.call_args.kwargs["customer_id"] == "cus_stored"
