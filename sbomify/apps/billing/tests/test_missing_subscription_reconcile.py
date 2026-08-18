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

``stripe_sync`` already knew how to settle this — mark the subscription
canceled, drop the dangling ids, invalidate the cache, all under
``select_for_update`` — but it recognised the condition by matching on the
error message, so the typed error introduced here reached it as neither
substring and left the branch unreachable. Wiring the two together settles
the workspace instead of only silencing the sweep, and clearing
``stripe_subscription_id`` is what stops both sweeps selecting it, so nothing
has to remember why it was skipped.
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

    def test_the_log_withholds_the_object_id(self) -> None:
        """Stripe puts the id in the message verbatim. CodeQL flagged the
        sweep's own line for that; dropping it there while this one still wrote
        it on the first occurrence would have moved the identifier rather than
        removed it."""
        from sbomify.apps.billing import stripe_client as stripe_client_module

        err = stripe.error.InvalidRequestError("No such subscription: 'sub_gone'", param="id", code="resource_missing")

        with (
            patch("stripe.Subscription.retrieve", side_effect=err),
            patch.object(stripe_client_module.logger, "error") as error_log,
            pytest.raises(StripeResourceMissingError),
        ):
            StripeClient().get_subscription("sub_gone")

        rendered = " ".join(str(a) for call in error_log.call_args_list for a in call.args)
        assert "sub_gone" not in rendered
        assert "resource_missing" in rendered

    def test_other_invalid_requests_keep_their_message(self) -> None:
        """The message is the only diagnosis for a malformed request, and it
        carries no object id."""
        from sbomify.apps.billing import stripe_client as stripe_client_module

        err = stripe.error.InvalidRequestError("Bad parameter: expand", param="expand", code="parameter_unknown")

        with (
            patch("stripe.Subscription.retrieve", side_effect=err),
            patch.object(stripe_client_module.logger, "error") as error_log,
            pytest.raises(StripeError),
        ):
            StripeClient().get_subscription("sub_x")

        rendered = " ".join(str(a) for call in error_log.call_args_list for a in call.args)
        assert "Bad parameter" in rendered


@pytest.mark.django_db
class TestTheSweepReconciles:
    def test_the_dangling_reference_is_cleared(self) -> None:
        """The defect this replaces: parking the workspace silenced the sweep
        without settling anything, so the dead id stayed on the row and every
        other code path kept tripping over it."""
        team = _expired_trial_team()

        _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))

        team.refresh_from_db()
        assert "stripe_subscription_id" not in team.billing_plan_limits

    def test_the_subscription_is_marked_canceled(self) -> None:
        team = _expired_trial_team()

        _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))

        team.refresh_from_db()
        assert team.billing_plan_limits["subscription_status"] == "canceled"

    def test_it_stops_asking_without_needing_a_marker(self) -> None:
        """Self-healing rather than remembered: both sweeps select on
        stripe_subscription_id being present, so clearing it is what takes the
        workspace out of them. A marker would have had to be cleared by hand."""
        team = _expired_trial_team()
        _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))

        second_sweep = MagicMock(side_effect=StripeResourceMissingError("gone"))
        _run_sweep(second_sweep)

        second_sweep.assert_not_called()

    def test_a_new_subscription_re_enters_the_sweep(self) -> None:
        """And re-enters on its own, because nothing was left behind to
        suppress it."""
        team = _expired_trial_team()
        _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))

        team.refresh_from_db()
        limits = team.billing_plan_limits
        limits["stripe_subscription_id"] = "sub_replacement"
        limits["stripe_customer_id"] = "cus_present"
        limits["is_trial"] = True
        limits["subscription_status"] = "trialing"
        team.billing_plan_limits = limits
        team.save()

        subscription = MagicMock()
        subscription.status = "active"
        get_subscription = MagicMock(return_value=subscription)
        _run_sweep(get_subscription)

        get_subscription.assert_called_once_with("sub_replacement")

    def test_the_row_is_re_read_under_a_lock(self) -> None:
        """A checkout completing during the Stripe round trip must not be
        reverted by the copy the sweep loaded beforehand."""
        from sbomify.apps.billing import stripe_sync

        team = _expired_trial_team()

        def _checkout_lands_mid_flight(_subscription_id: str):
            fresh = Team.objects.get(pk=team.pk)
            limits = fresh.billing_plan_limits
            limits["concurrent_write"] = "preserved"
            fresh.billing_plan_limits = limits
            fresh.save()
            raise StripeResourceMissingError("gone")

        assert stripe_sync.reconcile_missing_subscription  # the path under test
        _run_sweep(MagicMock(side_effect=_checkout_lands_mid_flight))

        team.refresh_from_db()
        assert team.billing_plan_limits.get("concurrent_write") == "preserved"


@pytest.mark.django_db
class TestEverythingElseKeepsRetrying:
    """Asserted against the stored subscription id rather than against the
    absence of a marker.

    An earlier version of this change parked the workspace behind a
    ``stripe_subscription_missing_at`` flag, and these tests checked that flag
    was not set. Reconciliation replaced the marker, so nothing can set it any
    more and those assertions could not fail — they would have passed against
    a version that wrongly reconciled every error. What actually distinguishes
    the cases now is whether the dangling reference was cleared.
    """

    def test_a_generic_stripe_failure_does_not_reconcile(self) -> None:
        """An outage or a malformed request may well succeed next time, so the
        subscription must not be marked canceled and its id must survive."""
        team = _expired_trial_team()

        _run_sweep(MagicMock(side_effect=StripeError("payment provider unavailable")))

        team.refresh_from_db()
        assert team.billing_plan_limits["stripe_subscription_id"] == "sub_gone"
        assert team.billing_plan_limits["subscription_status"] != "canceled"

    def test_an_unexpected_error_does_not_reconcile(self) -> None:
        team = _expired_trial_team()

        _run_sweep(MagicMock(side_effect=RuntimeError("boom")))

        team.refresh_from_db()
        assert team.billing_plan_limits["stripe_subscription_id"] == "sub_gone"
        assert team.billing_plan_limits["subscription_status"] != "canceled"

    def test_a_healthy_subscription_still_syncs(self) -> None:
        """The regression that would hurt most: the sweep's actual job."""
        team = _expired_trial_team()
        subscription = MagicMock()
        subscription.status = "active"

        _run_sweep(MagicMock(return_value=subscription))

        team.refresh_from_db()
        assert team.billing_plan_limits["subscription_status"] == "active"
        assert team.billing_plan_limits["is_trial"] is False
        assert team.billing_plan_limits["stripe_subscription_id"] == "sub_gone"


@pytest.mark.django_db
class TestAReplacementSubscriptionSurvives:
    """The lock stops a lost update; it does not stop acting on a stale premise.

    The decision to reconcile is made before the Stripe round trip, and a
    checkout can complete during it. Clearing unconditionally under the lock
    would then delete the subscription the customer had just paid for — the
    same harm the lock was added to prevent, reached from the other side.
    """

    def test_a_checkout_landing_mid_flight_is_not_undone(self) -> None:
        from sbomify.apps.billing.stripe_sync import reconcile_missing_subscription

        team = _expired_trial_team()

        # Stripe answered about sub_gone; by the time we settle, the row holds
        # a new subscription from a checkout that completed in the meantime.
        limits = team.billing_plan_limits
        limits["stripe_subscription_id"] = "sub_new_from_checkout"
        team.billing_plan_limits = limits
        team.save()

        reconcile_missing_subscription(team, "sub_gone")

        team.refresh_from_db()
        assert team.billing_plan_limits["stripe_subscription_id"] == "sub_new_from_checkout"
        assert team.billing_plan_limits["subscription_status"] != "canceled"

    def test_the_id_it_was_told_about_is_still_settled(self) -> None:
        """The ordinary case has to keep working."""
        from sbomify.apps.billing.stripe_sync import reconcile_missing_subscription

        team = _expired_trial_team()

        reconcile_missing_subscription(team, "sub_gone")

        team.refresh_from_db()
        assert "stripe_subscription_id" not in team.billing_plan_limits
        assert team.billing_plan_limits["subscription_status"] == "canceled"

    def test_a_no_op_does_not_invalidate_the_replacement_cache(self, monkeypatch) -> None:
        """Invalidating on a no-op would drop the entry belonging to whichever
        subscription replaced the missing one."""
        from sbomify.apps.billing import stripe_sync

        team = _expired_trial_team()
        limits = team.billing_plan_limits
        limits["stripe_subscription_id"] = "sub_new_from_checkout"
        team.billing_plan_limits = limits
        team.save()

        calls: list = []
        monkeypatch.setattr(stripe_sync, "invalidate_subscription_cache", lambda *a: calls.append(a))

        stripe_sync.reconcile_missing_subscription(team, "sub_gone")

        assert calls == []


@pytest.mark.django_db
class TestTheSweepReportsWhatHappened:
    """A no-op must not be announced or counted as a reconciliation."""

    def test_a_no_op_is_not_counted(self, caplog) -> None:
        from sbomify.apps.billing import tasks as billing_tasks

        team = _expired_trial_team()

        def _checkout_lands_mid_flight(_subscription_id: str):
            fresh = Team.objects.get(pk=team.pk)
            limits = fresh.billing_plan_limits
            limits["stripe_subscription_id"] = "sub_new_from_checkout"
            fresh.billing_plan_limits = limits
            fresh.save()
            raise StripeResourceMissingError("gone")

        with patch.object(billing_tasks.logger, "warning") as warning:
            _run_sweep(MagicMock(side_effect=_checkout_lands_mid_flight))

        assert not [c for c in warning.call_args_list if "cleared the dangling reference" in c.args[0]]

    def test_a_real_reconciliation_is_announced(self) -> None:
        from sbomify.apps.billing import tasks as billing_tasks

        _expired_trial_team()

        with patch.object(billing_tasks.logger, "warning") as warning:
            _run_sweep(MagicMock(side_effect=StripeResourceMissingError("gone")))

        assert [c for c in warning.call_args_list if "cleared the dangling reference" in c.args[0]]


@pytest.mark.django_db
class TestASettledWorkspaceIsNotStillTrialing:
    """``canceled`` and ``is_trial`` disagreeing is a state nothing else here
    produces.

    The trial-expiry path in ``billing_processing`` sets the two together, and
    the Stripe sync zeroes the remaining days whenever the subscription is not
    trialing. Reconciliation reached ``canceled`` by its own route and left the
    trial flags behind — and since the sweep that calls it selects expired
    trials, that was the ordinary result rather than an unusual one.
    """

    def test_the_trial_flags_are_cleared(self) -> None:
        from sbomify.apps.billing import stripe_sync

        team = _expired_trial_team()

        stripe_sync.reconcile_missing_subscription(team, "sub_gone")

        team.refresh_from_db()
        limits = team.billing_plan_limits
        assert limits["subscription_status"] == "canceled"
        assert limits["is_trial"] is False
        assert limits["trial_days_remaining"] == 0
        # Kept: it says when the trial ended rather than granting anything, and
        # the sweep reads it to decide what to look at.
        assert "trial_end" in limits

    def test_a_no_op_leaves_the_trial_alone(self) -> None:
        """The workspace moved on, so its trial is not this call's business."""
        from sbomify.apps.billing import stripe_sync

        team = _expired_trial_team()
        limits = team.billing_plan_limits
        limits["stripe_subscription_id"] = "sub_new_from_checkout"
        team.billing_plan_limits = limits
        team.save()

        stripe_sync.reconcile_missing_subscription(team, "sub_gone")

        team.refresh_from_db()
        assert team.billing_plan_limits["is_trial"] is True


@pytest.mark.django_db
class TestAnUnnamedSubscriptionSettlesNothing:
    def test_a_falsy_id_does_not_cancel_the_workspace(self) -> None:
        """With no id to compare against, a workspace that also holds none
        compares equal to it and would be canceled on the strength of a
        subscription nobody named."""
        from sbomify.apps.billing import stripe_sync

        team = Team.objects.create(name="No Subscription", billing_plan="community", billing_plan_limits={})

        assert stripe_sync.reconcile_missing_subscription(team, None) is False

        team.refresh_from_db()
        assert team.billing_plan_limits.get("subscription_status") != "canceled"


@pytest.mark.django_db
class TestTheSyncPathNamesTheWorkspace:
    """The other entry point into reconciliation, reached from views as well as
    from the sweep.

    It logged a bare "no longer exists", which said neither which workspace it
    concerned nor whether the reference was actually cleared — and the no-op
    branch declines to write, so the two are different outcomes.
    """

    def _sync_against_a_missing_subscription(self, team, monkeypatch, on_fetch=None):
        from sbomify.apps.billing import stripe_sync

        monkeypatch.setattr(
            stripe_sync.stripe_client,
            "get_subscription",
            MagicMock(side_effect=on_fetch or StripeResourceMissingError("gone")),
        )
        return stripe_sync.sync_subscription_from_stripe(team, force_refresh=True)

    def test_a_cleared_reference_names_the_workspace(self, monkeypatch) -> None:
        from sbomify.apps.billing import stripe_sync

        team = _expired_trial_team()

        with patch.object(stripe_sync.logger, "info") as info:
            self._sync_against_a_missing_subscription(team, monkeypatch)

        cleared = [c for c in info.call_args_list if "cleared it from workspace" in c.args[0]]
        assert cleared, "the sync path did not report clearing the reference"
        assert team.key in cleared[0].args

    def test_a_no_op_is_not_reported_as_a_clear(self, monkeypatch) -> None:
        from sbomify.apps.billing import stripe_sync

        team = _expired_trial_team()

        def _checkout_lands_mid_flight(_subscription_id: str):
            fresh = Team.objects.get(pk=team.pk)
            limits = fresh.billing_plan_limits
            limits["stripe_subscription_id"] = "sub_new_from_checkout"
            fresh.billing_plan_limits = limits
            fresh.save()
            raise StripeResourceMissingError("gone")

        with patch.object(stripe_sync.logger, "info") as info:
            self._sync_against_a_missing_subscription(team, monkeypatch, on_fetch=_checkout_lands_mid_flight)

        assert not [c for c in info.call_args_list if "cleared it from workspace" in c.args[0]]
        assert [c for c in info.call_args_list if "already moved on" in c.args[0]]


@pytest.mark.django_db
class TestCacheInvalidationNeedsBothHalvesOfTheKey:
    def test_a_missing_id_does_not_build_a_partial_key(self, monkeypatch) -> None:
        """Substituting "" for a missing id builds a key belonging to nothing —
        or to something else."""
        from sbomify.apps.billing import stripe_sync

        team = _expired_trial_team()
        calls: list = []
        monkeypatch.setattr(stripe_sync, "invalidate_subscription_cache", lambda *a: calls.append(a))

        stripe_sync.reconcile_missing_subscription(team, None)

        assert calls == []
