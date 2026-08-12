"""A subscription id that resolves to nothing will keep resolving to nothing.

Stripe answers ``resource_missing`` when an id we hold refers to no object
there — a subscription deleted out of band, or a record left behind by a
different Stripe account. The stale-trial sweep treated that like any other
Stripe failure: log it, count an error, come back tomorrow and ask again.

From staging, the same twelve subscription ids failing on every run:

    Invalid Stripe request: param=id, message=Request <id>: No such subscription: 'sub_...'
    Failed to sync team <key>: Invalid request to payment provider.

Nothing about that answer was ever going to change, so it was a permanent
daily error line per workspace with no path to resolution.

What a workspace should be entitled to once its subscription has vanished is
a billing decision. This does not make it — it parks the retry and says so
once, loudly, leaving the plan untouched.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.utils import timezone

from sbomify.apps.billing.stripe_client import (
    StripeClient,
    StripeError,
    StripeResourceMissingError,
)
from sbomify.apps.teams.models import Team


def _expired_trial_team(name: str = "Trial Team") -> Team:
    """A workspace whose trial ended yesterday — what the sweep looks for."""
    return Team.objects.create(
        name=name,
        billing_plan="business",
        billing_plan_limits={
            "stripe_subscription_id": "sub_gone",
            # The valid_billing_relationship constraint requires both ids or
            # neither, so the customer id is not optional scaffolding here.
            "stripe_customer_id": "cus_present",
            "is_trial": True,
            "subscription_status": "trialing",
            "trial_end": int(timezone.now().timestamp()) - 86400,
        },
    )


def _run_sweep(get_subscription: Any) -> None:
    from sbomify.apps.billing.tasks import check_stale_trials_task

    client = MagicMock()
    client.get_subscription = get_subscription
    with (
        patch("sbomify.apps.billing.tasks.is_billing_enabled", return_value=True),
        patch("sbomify.apps.billing.stripe_client.StripeClient", return_value=client),
    ):
        check_stale_trials_task()


class TestTheClientTellsTheCasesApart:
    """Everything downstream depends on ``resource_missing`` being
    distinguishable, and it was being flattened into a generic StripeError."""

    def test_a_missing_resource_raises_its_own_error(self) -> None:
        err = stripe.error.InvalidRequestError("No such subscription: 'sub_gone'", param="id", code="resource_missing")

        with patch("stripe.Subscription.retrieve", side_effect=err), pytest.raises(StripeResourceMissingError):
            StripeClient().get_subscription("sub_gone")

    def test_other_invalid_requests_are_unchanged(self) -> None:
        """The narrowness is the point: a malformed request is still a plain
        StripeError, and reconciling our stored id would be the wrong response
        to it."""
        err = stripe.error.InvalidRequestError("Bad parameter", param="expand", code="parameter_unknown")

        with patch("stripe.Subscription.retrieve", side_effect=err), pytest.raises(StripeError) as excinfo:
            StripeClient().get_subscription("sub_x")

        assert not isinstance(excinfo.value, StripeResourceMissingError)

    def test_it_is_still_a_stripe_error(self) -> None:
        """Existing ``except StripeError`` handlers must keep catching it."""
        assert issubclass(StripeResourceMissingError, StripeError)

    def test_the_log_names_the_code_it_classified_on(self) -> None:
        """Without the code in the line, the log says a request was invalid
        without saying which way, and the branch taken looks arbitrary."""
        from sbomify.apps.billing import stripe_client as stripe_client_module

        err = stripe.error.InvalidRequestError("No such subscription: 'sub_gone'", param="id", code="resource_missing")

        with (
            patch("stripe.Subscription.retrieve", side_effect=err),
            patch.object(stripe_client_module.logger, "error") as error_log,
            pytest.raises(StripeResourceMissingError),
        ):
            StripeClient().get_subscription("sub_gone")

        logged = error_log.call_args_list[0]
        assert "code=%s" in logged.args[0]
        assert "resource_missing" in logged.args


@pytest.mark.django_db
class TestTheSweepStopsAsking:
    def test_a_missing_subscription_is_marked(self) -> None:
        team = _expired_trial_team()

        _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))

        team.refresh_from_db()
        assert team.billing_plan_limits.get("stripe_subscription_missing_at")

    def test_a_marked_workspace_is_not_asked_again(self) -> None:
        """The defect. Without this the same id is re-queried every sweep,
        forever, for an answer that cannot change."""
        team = _expired_trial_team()
        _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))
        team.refresh_from_db()

        second_sweep = MagicMock(side_effect=StripeResourceMissingError("gone"))
        _run_sweep(second_sweep)

        second_sweep.assert_not_called()

    def test_the_marker_records_which_id_went_missing(self) -> None:
        """A bare timestamp cannot say what it was about, which is what makes
        the re-entry below possible."""
        team = _expired_trial_team()

        _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))

        team.refresh_from_db()
        assert team.billing_plan_limits["stripe_subscription_missing_id"] == "sub_gone"

    def test_a_new_subscription_re_enters_the_sweep(self) -> None:
        """The footgun in parking by timestamp alone: a workspace given a new
        subscription would stay parked forever if nobody thought to clear the
        marker, and the new subscription would never sync."""
        team = _expired_trial_team()
        _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))

        team.refresh_from_db()
        limits = team.billing_plan_limits
        limits["stripe_subscription_id"] = "sub_replacement"
        team.billing_plan_limits = limits
        team.save()

        subscription = MagicMock()
        subscription.status = "active"
        get_subscription = MagicMock(return_value=subscription)
        _run_sweep(get_subscription)

        get_subscription.assert_called_once_with("sub_replacement")

    def test_the_plan_is_left_alone(self) -> None:
        """Deliberately not decided here. Downgrading a workspace because a
        sync task could not find its subscription is a billing decision with
        real consequences for a real customer, and it belongs to a human."""
        team = _expired_trial_team()

        _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))

        team.refresh_from_db()
        assert team.billing_plan == "business"
        assert team.billing_plan_limits["stripe_subscription_id"] == "sub_gone"


@pytest.mark.django_db
class TestEverythingElseKeepsRetrying:
    def test_a_generic_stripe_failure_is_not_parked(self) -> None:
        """An outage or a malformed request may well succeed next time, so it
        must not be marked as permanently missing."""
        team = _expired_trial_team()

        _run_sweep(MagicMock(side_effect=StripeError("payment provider unavailable")))

        team.refresh_from_db()
        assert "stripe_subscription_missing_at" not in team.billing_plan_limits

    def test_an_unexpected_error_is_not_parked(self) -> None:
        team = _expired_trial_team()

        _run_sweep(MagicMock(side_effect=RuntimeError("boom")))

        team.refresh_from_db()
        assert "stripe_subscription_missing_at" not in team.billing_plan_limits

    def test_a_healthy_subscription_still_syncs(self) -> None:
        """The regression that would hurt most: the sweep's actual job."""
        team = _expired_trial_team()
        subscription = MagicMock()
        subscription.status = "active"

        _run_sweep(MagicMock(return_value=subscription))

        team.refresh_from_db()
        assert team.billing_plan_limits["subscription_status"] == "active"
        assert team.billing_plan_limits["is_trial"] is False
        assert "stripe_subscription_missing_at" not in team.billing_plan_limits
