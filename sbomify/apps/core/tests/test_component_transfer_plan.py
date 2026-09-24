"""Transferring a component follows the receiving workspace's plan.

The receiving workspace's component limit applies, and a workspace that cannot
hold private items receives the component as public.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan
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
    target = Team.objects.create(name="Other paid", billing_plan="business")
    target.key = number_to_random_token(target.pk)
    target.save(update_fields=["key"])
    Member.objects.create(team=target, user=sample_user, role="owner")
    component = Component.objects.create(
        name="moving", team=team_with_business_plan, visibility=Component.Visibility.PRIVATE
    )

    _transfer(sample_user, component, target)

    component.refresh_from_db()
    assert component.team == target
    assert component.visibility == Component.Visibility.PRIVATE
