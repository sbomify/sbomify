"""Saving a BillingPlan copies its limits onto the workspaces on that plan, and only then."""

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.teams.models import Team

pytestmark = pytest.mark.django_db

OLD_LIMITS = {"max_products": 1, "max_components": 5, "max_users": 2}
OTHER_KEYS = {"stripe_customer_id": "cus_123", "stripe_subscription_id": "sub_123", "subscription_status": "active"}


def _workspace(plan_key: str) -> Team:
    return Team.objects.create(
        name=f"On {plan_key}", billing_plan=plan_key, billing_plan_limits={**OLD_LIMITS, **OTHER_KEYS}
    )


def _plan(key: str) -> BillingPlan:
    return BillingPlan.objects.create(key=key, name=key, **OLD_LIMITS)


def test_saving_a_plan_updates_the_limits_of_workspaces_on_it():
    plan = _plan("propagated")
    on_plan = _workspace(plan.key)
    on_other_plan = _workspace("some_other_plan")

    plan.max_products = 10
    plan.max_components = 100
    plan.max_users = None
    plan.save()

    on_plan.refresh_from_db()
    on_other_plan.refresh_from_db()
    assert on_plan.billing_plan_limits == {
        "max_products": 10,
        "max_components": 100,
        "max_users": None,
        **OTHER_KEYS,
    }
    assert on_other_plan.billing_plan_limits == {**OLD_LIMITS, **OTHER_KEYS}


def test_creating_a_plan_leaves_workspaces_alone():
    workspace = _workspace("created")

    BillingPlan.objects.create(key="created", name="created", max_products=10, max_components=100, max_users=None)

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits == {**OLD_LIMITS, **OTHER_KEYS}


def test_a_save_flagged_to_skip_leaves_workspaces_alone():
    plan = _plan("flagged")
    workspace = _workspace(plan.key)

    plan._skip_team_update = True
    plan.max_products = 10
    plan.save()

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits == {**OLD_LIMITS, **OTHER_KEYS}


def test_a_save_of_other_fields_only_leaves_workspaces_alone():
    plan = _plan("price_only")
    workspace = _workspace(plan.key)

    plan.max_products = 10
    plan.promo_message = "Sale"
    plan.save(update_fields=["promo_message"])

    workspace.refresh_from_db()
    assert workspace.billing_plan_limits == {**OLD_LIMITS, **OTHER_KEYS}
