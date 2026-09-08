import contextlib

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from sbomify.apps.teams.models import Invitation, Member, Team


@pytest.fixture
def team(db):
    return Team.objects.create(name="Team A", key="team-a-key")


@pytest.fixture
def other_team(db):
    from sbomify.apps.billing.models import BillingPlan

    # Ensure plan exists for test
    BillingPlan.objects.get_or_create(
        key="business",
        defaults={
            "name": "Business",
            "description": "Business Plan",
            "max_users": 10,
        },
    )
    return Team.objects.create(name="Team B", key="team-b-key", billing_plan="business")


@pytest.fixture
def user_with_one_team(db, django_user_model, team):
    u = django_user_model.objects.create_user(username="user1", email="user1@test.com", password="password")
    Member.objects.create(user=u, team=team, role="admin", is_default_team=True)
    return u


@pytest.fixture
def owner(db, django_user_model, team):
    u = django_user_model.objects.create_user(username="owner", email="owner@test.com", password="password")
    Member.objects.create(user=u, team=team, role="owner", is_default_team=False)
    return u


def _setup_session(client, team, role):
    """Helper to set up session data for a user after force_login."""
    session = client.session
    session["current_team"] = {"key": team.key, "name": team.name, "role": role}
    session["user_teams"] = {team.key: {"role": role, "name": team.name}}
    session.save()


def test_removal_fallback_when_pending_invites_exist(client, owner, user_with_one_team, team, other_team):
    """
    Test that when a user is removed from their last workspace and has pending invites,
    we do NOT create a personal workspace, but handle it gracefully.
    """
    # 1. Setup: User has a pending invite to Team B (joinable)
    Invitation.objects.create(team=other_team, email=user_with_one_team.email, role="admin")

    # 2. Action: Owner removes User from Team A (their only team)
    client.force_login(owner)
    _setup_session(client, team, "owner")
    membership = Member.objects.get(user=user_with_one_team, team=team)

    url = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})
    response = client.delete(url)

    assert response.status_code == 302
    assert response.url == reverse("teams:team_settings", kwargs={"team_key": team.key})

    # 3. Verify: User removed
    assert not Member.objects.filter(pk=membership.pk).exists()

    # 4. Verify: NO new personal workspace created (because they have a pending invite)
    # The user should have 0 memberships now
    assert Member.objects.filter(user=user_with_one_team).count() == 0

    # 5. Verify: Specific message about "removed" without "personal workspace created"
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) > 0
    # The message should just say "removed from workspace", NOT "new personal workspace created"
    assert str(messages[0]) == "Member user1 removed from workspace."
    assert "personal workspace" not in str(messages[0])


def test_self_removal_fallback_when_pending_invites_exist(client, user_with_one_team, team, other_team):
    """
    Test that when a user REMOVES THEMSELVES from their last workspace and has pending invites,
    we redirect them to dashboard and clear session.
    """
    # 1. Setup: User has pending invite
    Invitation.objects.create(team=other_team, email=user_with_one_team.email, role="admin")

    # 2. Action: User leaves Team A
    client.force_login(user_with_one_team)
    _setup_session(client, team, "admin")
    membership = Member.objects.get(user=user_with_one_team, team=team)

    url = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})
    response = client.delete(url)

    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")

    # 3. Verify: Membership gone
    assert not Member.objects.filter(pk=membership.pk).exists()
    assert Member.objects.filter(user=user_with_one_team).count() == 0

    # 4. Check session cleared (implied by redirect to dashboard likely handling "state")
    # We can check specific message
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) > 0
    assert "Please accept a pending invitation or contact support" in str(messages[0])


@pytest.fixture
def paid_team(db):
    from sbomify.apps.billing.models import BillingPlan

    BillingPlan.objects.get_or_create(
        key="business",
        defaults={"name": "Business", "description": "Business Plan", "max_users": 10},
    )
    return Team.objects.create(
        name="Paid Workspace",
        key="paid-workspace-key",
        billing_plan="business",
        billing_plan_limits={
            "stripe_subscription_id": "sub_test123",
            "stripe_customer_id": "cus_test123",
        },
    )


@pytest.fixture
def paid_owner(db, django_user_model, paid_team, team):
    u = django_user_model.objects.create_user(username="paidowner", email="paid@test.com", password="password")
    Member.objects.create(user=u, team=team, role="owner", is_default_team=True)
    Member.objects.create(user=u, team=paid_team, role="owner", is_default_team=False)
    return u


def _delete_workspace(client, user, workspace, mocker, capture, settings, billing=True):
    """Delete from the dashboard.

    The cancellation is queued ``on_commit``, and the test transaction never
    commits, so the callbacks have to be captured or the task looks unqueued.
    """
    settings.BILLING = billing
    queued = mocker.patch("sbomify.apps.billing.tasks.cleanup_stripe_for_deleted_workspace.send")
    client.force_login(user)
    _setup_session(client, workspace, "owner")
    with capture(execute=True):
        response = client.post(
            reverse("teams:teams_dashboard"),
            {"_method": "DELETE", "key": workspace.key},
        )
    return response, queued


def test_deleting_a_workspace_cancels_its_subscription(
    client, paid_owner, paid_team, settings, mocker, django_capture_on_commit_callbacks
):
    """The subscription outlived the workspace and kept charging."""
    response, queued = _delete_workspace(
        client, paid_owner, paid_team, mocker, django_capture_on_commit_callbacks, settings=settings
    )

    assert response.status_code == 302
    assert not Team.objects.filter(pk=paid_team.pk).exists()
    queued.assert_called_once_with("sub_test123", "cus_test123", paid_team.key)


def test_deleting_a_free_workspace_queues_no_ids_to_cancel(
    client, paid_owner, paid_team, settings, mocker, django_capture_on_commit_callbacks
):
    """The task is still queued, and finds nothing for Stripe to do."""
    paid_team.billing_plan = "community"
    paid_team.billing_plan_limits = {}
    paid_team.save(update_fields=["billing_plan", "billing_plan_limits"])

    response, queued = _delete_workspace(
        client, paid_owner, paid_team, mocker, django_capture_on_commit_callbacks, settings=settings
    )

    assert response.status_code == 302
    assert not Team.objects.filter(pk=paid_team.pk).exists()
    assert queued.call_args[0][:2] == (None, None)


def test_the_delete_does_not_wait_on_stripe(
    client, paid_owner, paid_team, settings, mocker, django_capture_on_commit_callbacks
):
    """The row is gone before the call, so a slow Stripe must not hold the request."""
    client_cls = mocker.patch("sbomify.apps.billing.stripe_client.StripeClient")

    response, _ = _delete_workspace(
        client, paid_owner, paid_team, mocker, django_capture_on_commit_callbacks, settings=settings
    )

    assert response.status_code == 302
    assert not Team.objects.filter(pk=paid_team.pk).exists()
    client_cls.assert_not_called()


def test_a_permanent_stripe_failure_is_alerted_on(settings, mocker):
    """The alert is the whole safety net: without it a live subscription is silent."""
    from sbomify.apps.billing.stripe_client import StripeError
    from sbomify.apps.billing.tasks import cleanup_stripe_for_deleted_workspace

    settings.BILLING = True
    stripe = mocker.patch("sbomify.apps.billing.stripe_client.StripeClient")
    stripe.return_value.cancel_subscription.side_effect = StripeError("stripe is down")
    log = mocker.patch("sbomify.apps.billing.tasks.logger")

    cleanup_stripe_for_deleted_workspace("sub_test123", "cus_test123", "ws-key")

    log.critical.assert_called_once()
    assert "ws-key" in log.critical.call_args[0]


def test_the_worker_cancels_and_removes_the_customer(settings, mocker):
    from sbomify.apps.billing.tasks import cleanup_stripe_for_deleted_workspace

    settings.BILLING = True
    stripe = mocker.patch("sbomify.apps.billing.stripe_client.StripeClient")

    cleanup_stripe_for_deleted_workspace("sub_test123", "cus_test123", "ws-key")

    stripe.return_value.cancel_subscription.assert_called_once_with("sub_test123", prorate=True)
    stripe.return_value.delete_customer.assert_called_once_with("cus_test123")


def test_a_transient_stripe_failure_is_retried_not_alerted(settings, mocker):
    """An outage must come back to the queue, not stop at one CRITICAL with the
    subscription still billing."""
    import pytest as _pytest

    from sbomify.apps.billing.stripe_client import BillingRetryableError
    from sbomify.apps.billing.tasks import cleanup_stripe_for_deleted_workspace

    settings.BILLING = True
    stripe = mocker.patch("sbomify.apps.billing.stripe_client.StripeClient")
    stripe.return_value.cancel_subscription.side_effect = BillingRetryableError("stripe is unreachable")
    log = mocker.patch("sbomify.apps.billing.tasks.logger")

    with _pytest.raises(BillingRetryableError):
        cleanup_stripe_for_deleted_workspace("sub_test123", "cus_test123", "ws-key")

    log.critical.assert_not_called()


def test_account_deletion_stays_best_effort_on_a_transient_failure(mocker, settings):
    """It runs inline with nothing to retry it, so it must not raise into the flow."""
    from sbomify.apps.billing.stripe_client import BillingRetryableError
    from sbomify.apps.core.services.account_deletion import cleanup_stripe_for_workspace

    settings.BILLING = True
    stripe = mocker.patch("sbomify.apps.billing.stripe_client.StripeClient")
    stripe.return_value.cancel_subscription.side_effect = BillingRetryableError("stripe is unreachable")

    assert cleanup_stripe_for_workspace("sub_test123", "cus_test123") is False


def test_a_customer_only_cleanup_does_not_claim_a_cancellation(mocker, settings):
    """With no subscription there was nothing to cancel, and the log must not imply there was."""
    from sbomify.apps.billing.stripe_client import StripeError
    from sbomify.apps.core.services import account_deletion

    settings.BILLING = True
    stripe = mocker.patch("sbomify.apps.billing.stripe_client.StripeClient")
    stripe.return_value.delete_customer.side_effect = StripeError("gone wrong")
    log = mocker.patch.object(account_deletion, "logger")

    assert account_deletion.cleanup_stripe_for_workspace(None, "cus_test123") is False

    said = log.warning.call_args[0][0]
    assert "no subscription" in said
    assert "was cancelled" not in said


def test_stripe_is_left_alone_when_billing_is_disabled(settings, mocker):
    from sbomify.apps.billing.tasks import cleanup_stripe_for_deleted_workspace

    settings.BILLING = False
    stripe = mocker.patch("sbomify.apps.billing.stripe_client.StripeClient")

    cleanup_stripe_for_deleted_workspace("sub_test123", "cus_test123", "ws-key")

    stripe.assert_not_called()


def _delete_workspace_from_settings(client, user, workspace, mocker, capture, settings):
    """The Danger Zone button, which posts to team_general rather than the dashboard."""
    settings.BILLING = True
    queued = mocker.patch("sbomify.apps.billing.tasks.cleanup_stripe_for_deleted_workspace.send")
    client.force_login(user)
    _setup_session(client, workspace, "owner")
    with capture(execute=True):
        response = client.post(
            reverse("teams:team_general", kwargs={"team_key": workspace.key}),
            {"action": "delete"},
        )
    return response, queued


def test_deleting_a_workspace_from_settings_cancels_its_subscription(
    client, paid_owner, paid_team, settings, mocker, django_capture_on_commit_callbacks
):
    """The Danger Zone is the delete a user actually reaches.

    Its form posts to teams:team_general, not to the dashboard, so the
    cancellation the dashboard path performs has to happen here too or the
    subscription outlives the workspace and keeps charging.
    """
    response, queued = _delete_workspace_from_settings(
        client, paid_owner, paid_team, mocker, django_capture_on_commit_callbacks, settings=settings
    )

    assert response.status_code in (200, 302)
    assert not Team.objects.filter(pk=paid_team.pk).exists()
    queued.assert_called_once_with("sub_test123", "cus_test123", paid_team.key)


@pytest.mark.django_db(transaction=True)
def test_a_rolled_back_delete_cancels_nothing(paid_team, mocker):
    """Cancelling a subscription whose workspace still exists would be worse
    than leaving one running: the customer loses access and keeps the row.

    The helper queues on_commit, so a caller that wraps it in its own
    transaction and then fails cannot reach Stripe.
    """
    from django.db import transaction

    from sbomify.apps.teams.utils import delete_workspace_with_billing_cleanup

    queued = mocker.patch("sbomify.apps.billing.tasks.cleanup_stripe_for_deleted_workspace.send")
    # delete() nulls the instance's pk, so keep it to look the row up after.
    pk = paid_team.pk

    with contextlib.suppress(RuntimeError):
        with transaction.atomic():
            delete_workspace_with_billing_cleanup(paid_team)
            raise RuntimeError("the caller failed after deleting")

    assert Team.objects.filter(pk=pk).exists(), "the rollback should have restored it"
    queued.assert_not_called()
