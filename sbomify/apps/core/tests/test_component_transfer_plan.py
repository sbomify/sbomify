"""Transferring a component follows the receiving workspace's plan.

The receiving workspace gets the same billing checks as creating a component
there, and a workspace that cannot hold private items receives the component
as public.
"""

from __future__ import annotations

import datetime

import pytest
from django.conf import settings
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.apis import _check_billing_limits, _enforce_limit_under_lock
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


def _transfer(user, component: Component, target: Team):
    client = Client()
    setup_authenticated_client_session(client, component.team, user)
    return client.post(
        reverse("core:transfer_component", kwargs={"component_id": component.id}), {"team_key": target.key}
    )


def _paid_workspace(owner, **billing_plan_limits) -> Team:
    workspace = Team.objects.create(name="Other paid", billing_plan="business", billing_plan_limits=billing_plan_limits)
    Member.objects.create(team=workspace, user=owner, role="owner")
    return workspace


def test_a_workspace_at_its_component_limit_receives_nothing(
    sample_user, team_with_business_plan, team_with_community_plan
):
    limit = BillingPlan.objects.get(key="community").max_components
    for index in range(limit):
        Component.objects.create(name=f"existing-{index}", team=team_with_community_plan)
    component = Component.objects.create(name="moving", team=team_with_business_plan)

    response = _transfer(sample_user, component, team_with_community_plan)

    assert response.status_code == 403
    component.refresh_from_db()
    assert component.team == team_with_business_plan


def test_a_workspace_suspended_for_payment_receives_nothing(sample_user, team_with_business_plan):
    failed_at = timezone.now() - datetime.timedelta(days=settings.PAYMENT_GRACE_PERIOD_DAYS + 1)
    target = _paid_workspace(sample_user, subscription_status="past_due", payment_failed_at=failed_at.isoformat())
    component = Component.objects.create(name="moving", team=team_with_business_plan)

    response = _transfer(sample_user, component, target)

    assert response.status_code == 403
    assert b"suspended due to payment failure" in response.content
    component.refresh_from_db()
    assert component.team == team_with_business_plan


def test_a_key_with_no_workspace_behind_it_is_refused(sample_user, team_with_business_plan):
    # The same answer as for a workspace the caller does not administer.
    component = Component.objects.create(name="moving", team=team_with_business_plan)

    response = _transfer(sample_user, component, Team(key=number_to_random_token(10**9)))

    assert response.status_code == 403
    assert b"Only allowed for admins or owners of the target team" in response.content
    component.refresh_from_db()
    assert component.team == team_with_business_plan


@pytest.mark.parametrize("visibility", [Component.Visibility.PRIVATE, Component.Visibility.GATED])
def test_a_workspace_that_cannot_hold_private_items_receives_it_public(
    sample_user, team_with_business_plan, team_with_community_plan, visibility
):
    component = Component.objects.create(name="moving", team=team_with_business_plan, visibility=visibility)

    _transfer(sample_user, component, team_with_community_plan)

    component.refresh_from_db()
    assert component.team == team_with_community_plan
    assert component.visibility == Component.Visibility.PUBLIC


def test_a_paid_workspace_keeps_the_component_private(sample_user, team_with_business_plan, ensure_billing_plans):
    target = _paid_workspace(sample_user)
    component = Component.objects.create(
        name="moving", team=team_with_business_plan, visibility=Component.Visibility.PRIVATE
    )

    _transfer(sample_user, component, target)

    component.refresh_from_db()
    assert component.team == target
    assert component.visibility == Component.Visibility.PRIVATE


def test_the_plan_that_decides_visibility_is_read_under_the_lock(
    sample_user, team_with_business_plan, ensure_billing_plans, mocker
):
    target = _paid_workspace(sample_user)
    component = Component.objects.create(
        name="moving", team=team_with_business_plan, visibility=Component.Visibility.PRIVATE
    )

    def downgrade_then_take_lock(team_id: str, resource_type: str):
        # The plan changes after the view has read the workspace and before it locks it.
        Team.objects.filter(pk=target.pk).update(billing_plan="community")
        return _enforce_limit_under_lock(team_id, resource_type)

    mocker.patch("sbomify.apps.core.views._enforce_limit_under_lock", side_effect=downgrade_then_take_lock)

    _transfer(sample_user, component, target)

    component.refresh_from_db()
    assert component.team == target
    assert component.visibility == Component.Visibility.PUBLIC


def test_the_count_under_the_lock_decides(sample_user, team_with_business_plan, team_with_community_plan, mocker):
    limit = BillingPlan.objects.get(key="community").max_components
    for index in range(limit - 1):
        Component.objects.create(name=f"existing-{index}", team=team_with_community_plan)
    component = Component.objects.create(name="moving", team=team_with_business_plan)

    def pre_check_then_fill_the_last_slot(team_id: str, resource_type: str):
        # The pre-check still sees room. Only the count under the lock sees the workspace full.
        verdict = _check_billing_limits(team_id, resource_type)
        Component.objects.create(name="arrived", team=team_with_community_plan)
        return verdict

    mocker.patch("sbomify.apps.core.views._check_billing_limits", side_effect=pre_check_then_fill_the_last_slot)

    response = _transfer(sample_user, component, team_with_community_plan)

    assert response.status_code == 403
    assert f"You currently have {limit} components".encode() in response.content
    component.refresh_from_db()
    assert component.team == team_with_business_plan


def test_the_receiving_workspace_is_counted_under_its_lock_inside_the_transaction(
    sample_user, team_with_business_plan, ensure_billing_plans, mocker
):
    target = _paid_workspace(sample_user)
    component = Component.objects.create(name="moving", team=team_with_business_plan)
    depth: dict[str, int] = {}

    def at_depth(name: str, check):
        def record(team_id: str, resource_type: str):
            # Savepoint depth, not in_atomic_block: the test itself runs inside a transaction.
            depth[name] = len(transaction.get_connection().savepoint_ids)
            return check(team_id, resource_type)

        return record

    pre_check = mocker.patch(
        "sbomify.apps.core.views._check_billing_limits", side_effect=at_depth("pre-check", _check_billing_limits)
    )
    lock = mocker.patch(
        "sbomify.apps.core.views._enforce_limit_under_lock", side_effect=at_depth("lock", _enforce_limit_under_lock)
    )

    response = _transfer(sample_user, component, target)

    assert response.status_code == 302
    pre_check.assert_called_once_with(str(target.id), "component")
    lock.assert_called_once_with(str(target.id), "component")
    assert depth["lock"] > depth["pre-check"]
