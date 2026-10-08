"""Pages that check a stored scheduled downgrade must keep it while the cancel is still due or has happened."""

from unittest.mock import patch

import pytest
import stripe
from django.test import RequestFactory

from sbomify.apps.billing.billing_processing import check_billing_limits
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.notifications import check_downgrade_limit_exceeded
from sbomify.apps.core.apis import _check_billing_limits
from sbomify.apps.teams.models import Invitation

pytestmark = pytest.mark.django_db


def _subscription(**fields) -> stripe.Subscription:
    return stripe.Subscription.construct_from(
        {
            "id": "sub_test123",
            "object": "subscription",
            "status": "active",
            "cancel_at_period_end": False,
            "cancel_at": None,
            "customer": "cus_test123",
            "items": {"object": "list", "data": []},
            **fields,
        },
        "sk_test_x",
    )


ENDED_AT_ONCE = {"status": "canceled"}
# Only whether cancel_at is set matters, so a fixed date keeps the case the same on every run
CANCEL_AT_SET = {"cancel_at": 1893456000}
REACTIVATED: dict = {}


@pytest.fixture
def scheduled_team(team_with_business_plan, settings):
    settings.BILLING = True
    team = team_with_business_plan
    team.billing_plan_limits = {
        **team.billing_plan_limits,
        "stripe_subscription_id": "sub_test123",
        "stripe_customer_id": "cus_test123",
        "subscription_status": "active",
        "cancel_at_period_end": True,
        "scheduled_downgrade_plan": "community",
    }
    team.save()
    return team


def _run_bell(team):
    check_downgrade_limit_exceeded(team)


def _run_create_limit_check(team):
    _check_billing_limits(str(team.id), "component")


def _run_decorator(team):
    @check_billing_limits("component")
    def view(request):
        return None

    request = RequestFactory().post("/")
    request.session = {"current_workspace": {"key": team.key}}
    view(request)


READERS = [_run_bell, _run_create_limit_check, _run_decorator]


@pytest.mark.parametrize("reader", READERS)
@pytest.mark.parametrize("stripe_fields", [ENDED_AT_ONCE, CANCEL_AT_SET], ids=["ended_at_once", "cancel_at_set"])
@patch("sbomify.apps.billing.stripe_cache.get_cached_subscription")
def test_schedule_is_kept(mock_cache, stripe_fields, reader, scheduled_team):
    mock_cache.return_value = _subscription(**stripe_fields)

    reader(scheduled_team)

    scheduled_team.refresh_from_db()
    assert scheduled_team.billing_plan_limits["cancel_at_period_end"] is True
    assert scheduled_team.billing_plan_limits.get("scheduled_downgrade_plan") == "community"


@pytest.mark.parametrize("reader", READERS)
@patch("sbomify.apps.billing.stripe_cache.get_cached_subscription")
def test_reactivation_still_clears_the_schedule(mock_cache, reader, scheduled_team):
    mock_cache.return_value = _subscription(**REACTIVATED)

    reader(scheduled_team)

    scheduled_team.refresh_from_db()
    assert "scheduled_downgrade_plan" not in scheduled_team.billing_plan_limits


@patch("sbomify.apps.billing.stripe_cache.get_cached_subscription")
def test_the_bell_counts_seats_against_the_plan_being_dropped_to(mock_cache, scheduled_team, ensure_billing_plans):
    mock_cache.return_value = _subscription(cancel_at_period_end=True)
    BillingPlan.objects.filter(key="community").update(max_users=1)
    Invitation.objects.create(team=scheduled_team, email="ada@example.com", role="member")

    assert check_downgrade_limit_exceeded(scheduled_team) is not None
