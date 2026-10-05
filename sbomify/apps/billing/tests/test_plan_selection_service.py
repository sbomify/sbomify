"""The plan cards' downgrade guard, which is the only thing standing between a
workspace and a plan it does not fit.

Members is a real, enforced quota: there is a migration grandfathering teams
already over it, and the cards advertise it as "1 member" / "10 members". It was
the one quota the guard did not count, so a workspace with eight people could
pick the plan with room for one and find out from the invite form.
"""

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.plan_features import PLAN_FEATURES, features_lost_moving_to
from sbomify.apps.billing.services.plan_selection import build_plan_selection_context
from sbomify.apps.billing.tests.fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    sample_user,
)
from sbomify.apps.core.models import User
from sbomify.apps.teams.models import Member, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace_on_business(business_plan: BillingPlan, sample_user: User) -> Team:  # noqa: F811
    team = Team.objects.create(name="Downgrade Test", billing_plan="business")
    team.billing_plan_limits = {"subscription_status": "active", "max_products": 10, "max_components": 100}
    team.save()
    Member.objects.create(team=team, user=sample_user, role="owner")
    return team


def _add_members(team: Team, count: int) -> None:
    for index in range(count):
        user = User.objects.create_user(username=f"member{index}", email=f"member{index}@example.com")
        Member.objects.create(team=team, user=user, role="member")


def _context(rf, user: User, team: Team) -> dict:
    request = rf.get("/")
    request.user = user
    request.session = {}
    result = build_plan_selection_context(request, team, {})
    assert result.ok
    return result.value


def _downgrade(context: dict, key: str) -> dict:
    return context["plan_selection_data"]["downgradeLimits"][key]


def test_members_over_the_target_plan_block_the_downgrade(
    rf, sample_user: User, workspace_on_business: Team, community_plan: BillingPlan  # noqa: F811
) -> None:
    """Four extra members against a plan that holds one, with nothing else over."""
    community_plan.max_users = 1
    community_plan.save()
    _add_members(workspace_on_business, 4)

    community = _downgrade(_context(rf, sample_user, workspace_on_business), "community")

    assert community["exceeds"] is True
    assert community["resources"] == ["5 members (limit: 1)"]


def test_a_workspace_within_every_quota_may_downgrade(
    rf, sample_user: User, workspace_on_business: Team, community_plan: BillingPlan  # noqa: F811
) -> None:
    community_plan.max_users = 5
    community_plan.save()

    community = _downgrade(_context(rf, sample_user, workspace_on_business), "community")

    assert community["exceeds"] is False
    assert community["resources"] == []


def test_an_unlimited_quota_never_blocks(
    rf, sample_user: User, workspace_on_business: Team, enterprise_plan: BillingPlan  # noqa: F811
) -> None:
    """Enterprise stores its quotas as None, which must not compare as zero."""
    _add_members(workspace_on_business, 40)
    workspace_on_business.billing_plan = "enterprise"
    workspace_on_business.save()

    enterprise = _downgrade(_context(rf, sample_user, workspace_on_business), "enterprise")

    assert enterprise["exceeds"] is False


def test_a_past_due_workspace_still_gets_the_warning(
    rf, sample_user: User, workspace_on_business: Team, community_plan: BillingPlan  # noqa: F811
) -> None:
    """The guard used to be gated on an active subscription, so the workspace
    most likely to be downgrading got no warning at all."""
    community_plan.max_users = 1
    community_plan.save()
    _add_members(workspace_on_business, 4)
    workspace_on_business.billing_plan_limits = {"subscription_status": "past_due"}
    workspace_on_business.save()

    community = _downgrade(_context(rf, sample_user, workspace_on_business), "community")

    assert community["exceeds"] is True


def test_an_upgrade_is_never_guarded(
    rf, sample_user: User, workspace_on_business: Team, enterprise_plan: BillingPlan  # noqa: F811
) -> None:
    _add_members(workspace_on_business, 40)

    assert _downgrade(_context(rf, sample_user, workspace_on_business), "enterprise")["exceeds"] is False


def test_the_card_says_what_leaving_costs(
    rf, sample_user: User, workspace_on_business: Team, community_plan: BillingPlan  # noqa: F811
) -> None:
    context = _context(rf, sample_user, workspace_on_business)
    community = next(plan for plan in context["plans"] if plan["key"] == "community")
    business = next(plan for plan in context["plans"] if plan["key"] == "business")

    assert community["downgrade"] is True
    assert "Private products and components" in community["lost_features"]
    assert business["downgrade"] is False
    assert business["lost_features"] == []


def test_lost_features_skip_the_pointer_to_the_plan_below() -> None:
    lost = features_lost_moving_to("business", "community")

    assert "Everything in Community" not in lost
    assert set(lost) <= set(PLAN_FEATURES["business"])
