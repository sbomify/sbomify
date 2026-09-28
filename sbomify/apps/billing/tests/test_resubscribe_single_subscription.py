"""A new checkout leaves the workspace with one live subscription.

Stripe's checkout webhook and the browser's return from checkout race. Only the
webhook cancelled the subscription a checkout replaced, and only when it landed
first, so the usual order left both subscriptions billing. The return now
cancels it too, events for a subscription the workspace has replaced leave the
workspace alone, and the plan API refuses to open a second subscription.

Stripe reports the cancel at once, while the checkout that made it still holds
the workspace row. The last tests deliver that event from a second database
connection at exactly that point.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.contrib.messages import get_messages
from django.db import DatabaseError, connection, connections
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing import billing_processing
from sbomify.apps.billing.stripe_client import BillingRetryableError, StripeError, StripeResourceMissingError
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db


def _set_limits(team: Team, **limits) -> None:
    current = team.billing_plan_limits or {}
    current.update(limits)
    Team.objects.filter(pk=team.pk).update(billing_plan_limits=current)
    team.refresh_from_db()


def _subscription(sub_id: str, status: str, **fields) -> stripe.Subscription:
    return stripe.Subscription.construct_from(
        {
            "id": sub_id,
            "object": "subscription",
            "status": status,
            "customer": "cus_test123",
            "cancel_at": None,
            "cancel_at_period_end": False,
            "trial_end": None,
            "current_period_end": 1893456000,
            "metadata": {"plan_key": "business"},
            "items": {"object": "list", "data": []},
            **fields,
        },
        "sk_test_x",
    )


def _event(event_id: str) -> stripe.Event:
    return stripe.Event.construct_from({"id": event_id, "object": "event"}, "sk_test_x")


def _checkout_session(team: Team) -> stripe.checkout.Session:
    return stripe.checkout.Session.construct_from(
        {
            "id": "cs_new",
            "object": "checkout.session",
            "payment_status": "paid",
            "subscription": "sub_new",
            "customer": "cus_test123",
            "metadata": {"team_key": team.key, "plan_key": "business"},
            "amount_total": 19900,
            "currency": "usd",
        },
        "sk_test_x",
    )


@pytest.fixture
def stripe_client():
    """The shared StripeClient the views and webhook handlers both use, with Stripe replaced."""
    with (
        patch("sbomify.apps.billing.views.stripe_client") as views_client,
        patch("sbomify.apps.billing.billing_processing.stripe_client", views_client),
        patch("sbomify.apps.billing.views.sync_subscription_from_stripe"),
    ):
        views_client.get_customer.return_value = stripe.Customer.construct_from(
            {"id": "cus_test123", "object": "customer", "metadata": {}}, "sk_test_x"
        )
        yield views_client


def _stripe_has(stripe_client: MagicMock, **subscriptions: stripe.Subscription | Exception) -> None:
    """Serve these subscriptions by id, or raise the error given for one. Stripe has no other."""

    def get_subscription(sub_id: str) -> stripe.Subscription:
        found = subscriptions.get(sub_id, StripeResourceMissingError("No such subscription"))
        if isinstance(found, Exception):
            raise found
        return found

    stripe_client.get_subscription.side_effect = get_subscription


def _complete_checkout(checkout: str, team: Team, user) -> None:
    """Finish the checkout through the browser's return, or through Stripe's webhook."""
    if checkout == "return":
        client = Client()
        client.force_login(user)
        client.get(reverse("billing:billing_return") + "?session_id=cs_new")
    else:
        billing_processing.handle_checkout_completed(_checkout_session(team))


def test_return_from_checkout_cancels_the_subscription_it_replaces(stripe_client, team_with_business_plan, sample_user):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_old", subscription_status="past_due")
    stripe_client.get_checkout_session.return_value = _checkout_session(team_with_business_plan)
    _stripe_has(stripe_client, sub_old=_subscription("sub_old", "past_due"), sub_new=_subscription("sub_new", "active"))

    _complete_checkout("return", team_with_business_plan, sample_user)

    stripe_client.cancel_subscription.assert_called_once_with("sub_old")
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_new"


@pytest.mark.parametrize("checkout", ["return", "webhook"])
@pytest.mark.parametrize("replaced", ["canceled", "incomplete_expired", "missing"])
def test_a_replaced_subscription_that_has_ended_is_not_cancelled_again(
    checkout, replaced, stripe_client, team_with_business_plan, sample_user
):
    """Stripe refuses to cancel an ended subscription, and cannot cancel one it no longer has."""
    held = {"sub_new": _subscription("sub_new", "active")}
    if replaced != "missing":
        held["sub_old"] = _subscription("sub_old", replaced)
    _set_limits(
        team_with_business_plan,
        stripe_subscription_id="sub_old",
        subscription_status="active" if replaced == "missing" else replaced,
    )
    stripe_client.get_checkout_session.return_value = _checkout_session(team_with_business_plan)
    _stripe_has(stripe_client, **held)

    _complete_checkout(checkout, team_with_business_plan, sample_user)

    stripe_client.cancel_subscription.assert_not_called()
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_new"


def _stripe_fails(stripe_client: MagicMock, failing: str) -> None:
    """Stripe is unavailable when the checkout reads, or cancels, the subscription it replaces."""
    outage = BillingRetryableError("Stripe is unavailable")
    _stripe_has(
        stripe_client,
        sub_old=outage if failing == "read" else _subscription("sub_old", "past_due"),
        sub_new=_subscription("sub_new", "active"),
    )
    if failing == "cancel":
        stripe_client.cancel_subscription.side_effect = outage


@pytest.mark.parametrize("failing", ["read", "cancel"])
def test_return_from_checkout_keeps_the_old_subscription_when_the_cancel_fails(
    failing, stripe_client, team_with_business_plan, sample_user
):
    """Storing the new subscription without the cancel would leave both billing."""
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_old", subscription_status="past_due")
    stripe_client.get_checkout_session.return_value = _checkout_session(team_with_business_plan)
    _stripe_fails(stripe_client, failing)
    client = Client()
    client.force_login(sample_user)

    response = client.get(reverse("billing:billing_return") + "?session_id=cs_new")

    assert [str(message) for message in get_messages(response.wsgi_request)] == [
        "Payment processing error. Please contact support if the issue persists."
    ]
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_old"


@pytest.mark.parametrize("failing", ["read", "cancel"])
def test_checkout_webhook_retries_when_the_cancel_fails(failing, stripe_client, team_with_business_plan):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_old", subscription_status="past_due")
    _stripe_fails(stripe_client, failing)

    with pytest.raises(BillingRetryableError):
        billing_processing.handle_checkout_completed(_checkout_session(team_with_business_plan))

    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_old"


def test_event_for_a_replaced_subscription_leaves_the_workspace_alone(stripe_client, team_with_business_plan):
    """It emails no one and reports nothing to analytics about the old subscription."""
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_new", subscription_status="active")

    with (
        patch("sbomify.apps.billing.billing_processing.notify_billing_managers") as notify,
        patch("sbomify.apps.core.posthog_service.capture") as capture,
        patch("sbomify.apps.core.posthog_service.group_identify") as group_identify,
    ):
        billing_processing.handle_subscription_updated(
            _subscription("sub_old", "canceled"), event=_event("evt_old_canceled")
        )

    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_new"
    assert team_with_business_plan.billing_plan_limits["subscription_status"] == "active"
    notify.assert_not_called()
    capture.assert_not_called()
    group_identify.assert_not_called()


def test_event_for_the_replacement_applies_when_the_stored_subscription_ended(stripe_client, team_with_business_plan):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_old", subscription_status="canceled")

    billing_processing.handle_subscription_updated(_subscription("sub_new", "active"), event=_event("evt_new_active"))

    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan_limits["stripe_subscription_id"] == "sub_new"
    assert team_with_business_plan.billing_plan_limits["subscription_status"] == "active"


@pytest.mark.parametrize("status", ["not_a_status"])
def test_an_unknown_subscription_status_is_refused(status, stripe_client, team_with_business_plan):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_live", subscription_status="active")

    with pytest.raises(StripeError, match=f"Invalid subscription status: {status}"):
        billing_processing.handle_subscription_updated(_subscription("sub_live", status), event=_event("evt_status"))


def test_the_downgrade_rolls_back_when_the_visibility_change_fails(team_with_business_plan, ensure_billing_plans):
    """Committed alone, the plan change marks the event processed and the retry leaves the components private."""
    team = team_with_business_plan
    _set_limits(
        team,
        stripe_subscription_id="sub_old",
        subscription_status="active",
        cancel_at_period_end=True,
        scheduled_downgrade_plan="community",
    )
    private = [
        Component.objects.create(name=f"Private {i}", team=team, visibility=Component.Visibility.PRIVATE).pk
        for i in range(2)
    ]
    ended = _subscription("sub_old", "canceled")
    event = _event("evt_old_deleted")

    with (
        patch(
            "sbomify.apps.billing.billing_processing.apply_community_downgrade",
            side_effect=DatabaseError,
        ),
        pytest.raises(BillingRetryableError),
    ):
        billing_processing.handle_subscription_deleted(ended, event=event)

    team.refresh_from_db()
    assert team.billing_plan == "business"

    billing_processing.handle_subscription_deleted(ended, event=event)

    team.refresh_from_db()
    assert team.billing_plan == "community"
    assert set(Component.objects.filter(pk__in=private).values_list("visibility", flat=True)) == {
        Component.Visibility.PUBLIC
    }


def _change_plan(client: Client, team: Team):
    return client.post(
        reverse("api-1:change_plan"),
        json.dumps({"plan": "business", "billing_period": "monthly", "team_key": team.key}),
        content_type="application/json",
    )


@pytest.mark.parametrize("status", ["active", "trialing", "past_due", "incomplete"])
def test_plan_api_refuses_a_second_subscription(status, team_with_business_plan, sample_user):
    _set_limits(team_with_business_plan, stripe_subscription_id="sub_live", subscription_status=status)
    client = Client()
    client.force_login(sample_user)
    stripe_api = MagicMock()

    with patch("sbomify.apps.billing.apis.get_stripe_client", return_value=stripe_api):
        response = _change_plan(client, team_with_business_plan)

    assert response.status_code == 409
    stripe_api.create_checkout_session.assert_not_called()


def test_plan_api_checks_out_on_the_stored_customer(team_with_business_plan, sample_user):
    _set_limits(
        team_with_business_plan,
        stripe_customer_id="cus_stored",
        stripe_subscription_id="sub_ended",
        subscription_status="canceled",
    )
    client = Client()
    client.force_login(sample_user)
    stripe_api = MagicMock()
    stripe_api.create_checkout_session.return_value = stripe.checkout.Session.construct_from(
        {"id": "cs_plan", "object": "checkout.session", "url": "https://checkout.example.com/session"}, "sk_test_x"
    )

    with patch("sbomify.apps.billing.apis.get_stripe_client", return_value=stripe_api):
        response = _change_plan(client, team_with_business_plan)

    assert response.status_code == 200
    assert stripe_api.create_checkout_session.call_args.kwargs["customer_id"] == "cus_stored"


class _SecondWorker(threading.Thread):
    """Delivers one webhook on its own database connection, as another worker process would."""

    def __init__(self, deliver: Callable[[], None]) -> None:
        super().__init__()
        self.deliver = deliver
        self.backend_pid: int | None = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                self.backend_pid = cursor.fetchone()[0]
            self.deliver()
        except BaseException as exc:
            self.error = exc
        finally:
            connections.close_all()

    def start_and_wait(self) -> None:
        """Start, and return once the delivery has finished or is waiting for a row another connection holds."""
        self.start()
        deadline = time.monotonic() + 10
        with connection.cursor() as cursor:
            while self.is_alive():
                if self.backend_pid is not None:
                    cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [self.backend_pid])
                    if cursor.fetchone()[0]:
                        return
                if time.monotonic() > deadline:
                    pytest.fail("the webhook neither finished nor waited for the workspace row")
                time.sleep(0.01)


def _deliver_when_cancelled(stripe_client: MagicMock, handler: Callable[..., None], status: str) -> list[_SecondWorker]:
    """Deliver the replaced subscription's event the moment the checkout cancels it."""
    workers: list[_SecondWorker] = []

    def cancel(sub_id: str) -> None:
        event = _event(f"evt_{sub_id}_{status}")
        worker = _SecondWorker(lambda: handler(_subscription(sub_id, status), event=event))
        workers.append(worker)
        worker.start_and_wait()

    stripe_client.cancel_subscription.side_effect = cancel
    return workers


def _finish(workers: list[_SecondWorker]) -> None:
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive(), "the webhook never finished"
        assert worker.error is None, f"the webhook failed: {worker.error!r}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("checkout", ["return", "webhook"])
@pytest.mark.parametrize("replaced", ["past_due", "cancelling"])
def test_the_replaced_subscription_ending_leaves_the_new_one_alone(
    checkout, replaced, stripe_client, team_with_business_plan, sample_user, ensure_billing_plans
):
    team = team_with_business_plan
    if replaced == "past_due":
        _set_limits(team, stripe_subscription_id="sub_old", subscription_status="past_due")
        old = _subscription("sub_old", "past_due")
    else:
        _set_limits(
            team,
            stripe_subscription_id="sub_old",
            subscription_status="active",
            cancel_at_period_end=True,
            scheduled_downgrade_plan="community",
        )
        old = _subscription("sub_old", "active", cancel_at_period_end=True)
    private = [
        Component.objects.create(name=f"Private {i}", team=team, visibility=Component.Visibility.PRIVATE).pk
        for i in range(2)
    ]
    stripe_client.get_checkout_session.return_value = _checkout_session(team)
    _stripe_has(stripe_client, sub_old=old, sub_new=_subscription("sub_new", "active"))
    workers = _deliver_when_cancelled(stripe_client, billing_processing.handle_subscription_deleted, "canceled")

    with patch("sbomify.apps.billing.billing_processing.notify_billing_managers") as notify:
        _complete_checkout(checkout, team, sample_user)
        _finish(workers)

    stripe_client.cancel_subscription.assert_called_once_with("sub_old")
    team.refresh_from_db()
    assert team.billing_plan == "business"
    assert team.billing_plan_limits["stripe_subscription_id"] == "sub_new"
    assert team.billing_plan_limits["subscription_status"] == "active"
    assert set(Component.objects.filter(pk__in=private).values_list("visibility", flat=True)) == {
        Component.Visibility.PRIVATE
    }
    notify.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_a_late_update_for_the_replaced_subscription_leaves_the_new_one_stored(
    stripe_client, team_with_business_plan, sample_user
):
    team = team_with_business_plan
    _set_limits(team, stripe_subscription_id="sub_old", subscription_status="past_due")
    stripe_client.get_checkout_session.return_value = _checkout_session(team)
    _stripe_has(stripe_client, sub_old=_subscription("sub_old", "past_due"), sub_new=_subscription("sub_new", "active"))
    workers = _deliver_when_cancelled(stripe_client, billing_processing.handle_subscription_updated, "past_due")

    with patch("sbomify.apps.billing.billing_processing.notify_billing_managers"):
        _complete_checkout("return", team, sample_user)
        _finish(workers)

    team.refresh_from_db()
    assert team.billing_plan_limits["stripe_subscription_id"] == "sub_new"
    assert team.billing_plan_limits["subscription_status"] == "active"
