"""The plan cards' downgrade guard, which is the only thing standing between a
workspace and a plan it does not fit.

Members is a real, enforced quota: there is a migration grandfathering teams
already over it, and the cards advertise it as "1 member" / "10 members". It was
the one quota the guard did not count, so a workspace with eight people could
pick the plan with room for one and find out from the invite form.
"""

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.plan_features import PLAN_FEATURES, effective_features, features_lost_moving_to
from sbomify.apps.billing.services.plan_selection import build_plan_selection_context
from sbomify.apps.billing.tests.fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    sample_user,
)
from sbomify.apps.core.models import Component, User
from sbomify.apps.oidc.models import OIDCBinding
from sbomify.apps.teams.models import Invitation, Member, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace_on_business(business_plan: BillingPlan, sample_user: User) -> Team:  # noqa: F811
    team = Team.objects.create(name="Downgrade Test", billing_plan="business")
    team.billing_plan_limits = {"subscription_status": "active", "max_products": 10, "max_components": 100}
    team.save()
    Member.objects.create(team=team, user=sample_user, role="owner")
    return team


def _tomorrow() -> datetime:
    return timezone.now() + timedelta(days=1)


def _yesterday() -> datetime:
    return timezone.now() - timedelta(days=1)


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
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    community_plan: BillingPlan,  # noqa: F811
) -> None:
    """Four extra members against a plan that holds one, with nothing else over."""
    community_plan.max_users = 1
    community_plan.save()
    _add_members(workspace_on_business, 4)

    community = _downgrade(_context(rf, sample_user, workspace_on_business), "community")

    assert community["exceeds"] is True
    assert community["resources"] == ["5 members (limit: 1)"]


def test_a_workspace_within_every_quota_may_downgrade(
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    community_plan: BillingPlan,  # noqa: F811
) -> None:
    community_plan.max_users = 5
    community_plan.save()

    community = _downgrade(_context(rf, sample_user, workspace_on_business), "community")

    assert community["exceeds"] is False
    assert community["resources"] == []


def test_an_unlimited_quota_never_blocks(
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    enterprise_plan: BillingPlan,  # noqa: F811
) -> None:
    """Enterprise stores its quotas as None, which must not compare as zero."""
    _add_members(workspace_on_business, 40)
    workspace_on_business.billing_plan = "enterprise"
    workspace_on_business.save()

    enterprise = _downgrade(_context(rf, sample_user, workspace_on_business), "enterprise")

    assert enterprise["exceeds"] is False


def test_a_past_due_workspace_still_gets_the_warning(
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    community_plan: BillingPlan,  # noqa: F811
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
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    enterprise_plan: BillingPlan,  # noqa: F811
) -> None:
    _add_members(workspace_on_business, 40)

    assert _downgrade(_context(rf, sample_user, workspace_on_business), "enterprise")["exceeds"] is False


def test_the_card_says_what_leaving_costs(
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    community_plan: BillingPlan,  # noqa: F811
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


def test_a_tier_carries_everything_below_it() -> None:
    """The tuples are deltas. Enterprise names what Business does not have and
    points at it, so reading a tuple as a whole plan understates it."""
    assert set(effective_features("business")) > set(effective_features("community"))
    assert set(effective_features("enterprise")) > set(effective_features("business"))
    assert not any(feature.startswith("Everything in") for feature in effective_features("enterprise"))


def test_leaving_the_top_tier_counts_the_middle_one_too() -> None:
    """Diffing the two tuples directly dropped every Business feature from an
    Enterprise-to-Community move, which is most of what the workspace loses."""
    lost = features_lost_moving_to("enterprise", "community")

    assert "Private products and components" in lost
    assert "Custom Dependency Track servers" in lost
    assert set(features_lost_moving_to("business", "community")) <= set(lost)


def test_one_step_down_loses_only_that_step() -> None:
    lost = features_lost_moving_to("enterprise", "business")

    assert "Custom Dependency Track servers" in lost
    assert "Private products and components" not in lost


def test_pending_invitations_count_against_the_seat_quota(
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    community_plan: BillingPlan,  # noqa: F811
) -> None:
    """An invitation holds a seat, and the seat check counts it. A guard that
    did not would wave through a plan whose last place is already spoken for."""
    community_plan.max_users = 2
    community_plan.save()
    _add_members(workspace_on_business, 1)
    Invitation.objects.create(
        team=workspace_on_business, email="invited@example.com", role="member", expires_at=_tomorrow()
    )

    community = _downgrade(_context(rf, sample_user, workspace_on_business), "community")

    assert community["exceeds"] is True
    assert community["resources"] == ["3 members and pending invitations (limit: 2)"]


def test_an_expired_invitation_holds_no_seat(
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    community_plan: BillingPlan,  # noqa: F811
) -> None:
    community_plan.max_users = 2
    community_plan.save()
    _add_members(workspace_on_business, 1)
    Invitation.objects.create(
        team=workspace_on_business, email="lapsed@example.com", role="member", expires_at=_yesterday()
    )

    community = _downgrade(_context(rf, sample_user, workspace_on_business), "community")

    assert community["exceeds"] is False


def test_bot_publishers_are_not_seats(
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    community_plan: BillingPlan,  # noqa: F811
) -> None:
    """A bot Member is an OIDC binding, not a person. Counting it would block a
    workspace from a plan it fits."""
    community_plan.max_users = 2
    community_plan.save()
    _add_members(workspace_on_business, 1)
    bot = User.objects.create_user(username="publisher", email="publisher@example.com")
    OIDCBinding.objects.create(
        component=Component.objects.create(name="published-by-ci", team=workspace_on_business),
        provider=OIDCBinding.PROVIDER_GITHUB,
        repository="example/widget",
        repository_id=12345,
        repository_owner_id=67890,
        bot_user=bot,
        created_by=sample_user,
    )
    # A bot Member is only accepted because the binding above names this user.
    Member.objects.create(team=workspace_on_business, user=bot, role="bot")

    community = _downgrade(_context(rf, sample_user, workspace_on_business), "community")

    assert community["exceeds"] is False


def test_only_leaving_a_live_subscription_runs_to_the_period_end(
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    community_plan: BillingPlan,  # noqa: F811
    enterprise_plan: BillingPlan,  # noqa: F811
) -> None:
    """Enterprise to Business is a subscription update, and a workspace with
    nothing to cancel changes over straight away."""
    context = _context(rf, sample_user, workspace_on_business)
    assert next(p for p in context["plans"] if p["key"] == "community")["ends_subscription"] is True

    workspace_on_business.billing_plan = "enterprise"
    workspace_on_business.save()
    context = _context(rf, sample_user, workspace_on_business)
    assert next(p for p in context["plans"] if p["key"] == "business")["ends_subscription"] is False
    assert next(p for p in context["plans"] if p["key"] == "community")["ends_subscription"] is True


def test_a_workspace_with_no_live_subscription_changes_over_at_once(
    rf,
    sample_user: User,  # noqa: F811
    workspace_on_business: Team,
    community_plan: BillingPlan,  # noqa: F811
) -> None:
    workspace_on_business.billing_plan_limits = {"subscription_status": "canceled"}
    workspace_on_business.save()

    community = next(p for p in _context(rf, sample_user, workspace_on_business)["plans"] if p["key"] == "community")

    assert community["downgrade"] is True
    assert community["ends_subscription"] is False
