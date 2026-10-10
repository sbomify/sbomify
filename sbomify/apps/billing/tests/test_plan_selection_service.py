"""The plan cards' downgrade guard, which is the only thing standing between a
workspace and a plan it does not fit.

Members is a real, enforced quota: there is a migration grandfathering teams
already over it, and the cards advertise it as "1 member" / "10 members". It was
the one quota the guard did not count, so a workspace with eight people could
pick the plan with room for one and find out from the invite form.
"""

from datetime import timedelta

import pytest
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest
from django.test import RequestFactory
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.plan_features import PLAN_FEATURES, effective_features, features_lost_moving_to
from sbomify.apps.billing.services.plan_selection import build_plan_selection_context, check_downgrade
from sbomify.apps.billing.tests.fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    sample_user,
)
from sbomify.apps.core.models import User
from sbomify.apps.teams.models import Invitation, Member, Team

pytestmark = pytest.mark.django_db


def _request() -> HttpRequest:
    request = RequestFactory().get("/")
    SessionMiddleware(lambda req: None).process_request(request)
    return request


@pytest.fixture
def plans(db) -> None:
    BillingPlan.objects.update_or_create(
        key="community",
        defaults={"name": "Community", "max_users": 1, "max_products": 1, "max_components": 5},
    )
    BillingPlan.objects.update_or_create(
        key="business",
        defaults={"name": "Business", "max_users": 10, "max_products": 10, "max_components": 100},
    )


@pytest.fixture
def subscribed_workspace(db, plans) -> Team:
    workspace = Team.objects.create(
        name="Downgrade test",
        key="dg-test",
        billing_plan="business",
        billing_plan_limits={
            "subscription_status": "active",
            "stripe_customer_id": "cus_x",
            "stripe_subscription_id": "sub_x",
        },
    )
    return workspace


def _add_members(workspace: Team, count: int) -> None:
    for index in range(count):
        user = User.objects.create(username=f"member-{index}-{workspace.key}", email=f"m{index}@example.com")
        Member.objects.create(user=user, team=workspace, role="member")


def _add_bot(workspace: Team) -> None:
    """A synthetic OIDC identity, provisioned the way the binding flow does.

    A pre_save guard reserves ``role="bot"`` for that flow and takes this flag
    as its opt-out, so this is the only way to write the row the guard protects.
    """
    user = User.objects.create(username=f"oidc-bot-{workspace.key}", email="bot@example.com")
    member = Member(user=user, team=workspace, role="bot")
    member._is_oidc_bot_provisioning = True
    member.save()


def _community(context: dict) -> dict:
    return context["plan_selection_data"]["downgradeLimits"]["community"]


@pytest.mark.django_db
def test_members_over_the_target_cap_block_the_downgrade(subscribed_workspace) -> None:
    _add_members(subscribed_workspace, 3)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    limits = _community(context)
    assert limits["exceeds"] is True
    assert limits["resources"] == ["3 members (limit: 1)"]


@pytest.mark.django_db
def test_a_workspace_that_fits_the_target_plan_is_not_blocked(subscribed_workspace) -> None:
    _add_members(subscribed_workspace, 1)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    assert _community(context) == {"exceeds": False, "resources": []}


@pytest.mark.django_db
def test_the_cheaper_plan_is_marked_as_a_downgrade(subscribed_workspace) -> None:
    _add_members(subscribed_workspace, 1)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    by_key = {plan["key"]: plan for plan in context["plans"]}
    assert by_key["community"]["downgrade"] is True
    assert by_key["business"]["downgrade"] is False
    assert by_key["business"]["current"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["past_due", "incomplete"])
def test_a_live_subscription_behind_on_payment_is_still_guarded(subscribed_workspace, status) -> None:
    """Stripe still counts these as the subscription the workspace pays through."""
    subscribed_workspace.billing_plan_limits = {
        **subscribed_workspace.billing_plan_limits,
        "subscription_status": status,
    }
    subscribed_workspace.save()
    _add_members(subscribed_workspace, 3)
    community = BillingPlan.objects.get(key="community")

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    assert _community(context)["exceeds"] is True
    assert check_downgrade(subscribed_workspace, community).status_code == 409


@pytest.mark.django_db
def test_an_unsubscribed_workspace_is_never_blocked(plans) -> None:
    workspace = Team.objects.create(name="Free", key="free-test", billing_plan="business", billing_plan_limits={})
    _add_members(workspace, 5)

    context = build_plan_selection_context(_request(), workspace, {}).value

    assert _community(context)["exceeds"] is False


@pytest.mark.django_db
def test_a_pending_invitation_counts_against_the_target_cap(subscribed_workspace) -> None:
    """The invite path treats an unexpired invitation as a seat already taken,
    so a workspace one invitation over the cap must not be waved onto the plan."""
    _add_members(subscribed_workspace, 1)
    Invitation.objects.create(team=subscribed_workspace, email="ada@example.com", role="member")

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    limits = _community(context)
    assert limits["exceeds"] is True
    assert limits["resources"] == ["2 members (limit: 1)"]


@pytest.mark.django_db
def test_an_expired_invitation_holds_no_seat(subscribed_workspace) -> None:
    _add_members(subscribed_workspace, 1)
    Invitation.objects.create(
        team=subscribed_workspace,
        email="grace@example.com",
        role="member",
        expires_at=timezone.now() - timedelta(days=1),
    )

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    assert _community(context) == {"exceeds": False, "resources": []}


@pytest.mark.django_db
def test_a_bot_member_does_not_block_the_downgrade(subscribed_workspace) -> None:
    """Bot members are synthetic OIDC identities, not seats, and the invite path
    does not count them either."""
    _add_members(subscribed_workspace, 1)
    _add_bot(subscribed_workspace)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    assert _community(context) == {"exceeds": False, "resources": []}


@pytest.mark.django_db
def test_the_usage_card_counts_people_not_seats(subscribed_workspace) -> None:
    """The usage card reports members the way the members tab does: a held seat
    is not a person, and a bot is not one either."""
    _add_members(subscribed_workspace, 2)
    Invitation.objects.create(team=subscribed_workspace, email="ada@example.com", role="member")
    _add_bot(subscribed_workspace)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    assert context["usage"]["users"] == 2


@pytest.fixture
def workspace_on_business(business_plan: BillingPlan, sample_user: User) -> Team:  # noqa: F811
    team = Team.objects.create(name="Downgrade Test", billing_plan="business")
    team.billing_plan_limits = {"subscription_status": "active", "max_products": 10, "max_components": 100}
    team.save()
    Member.objects.create(team=team, user=sample_user, role="owner")
    return team


def _context(rf, user: User, team: Team) -> dict:
    request = rf.get("/")
    request.user = user
    request.session = {}
    result = build_plan_selection_context(request, team, {})
    assert result.ok
    return result.value


def _downgrade(context: dict, key: str) -> dict:
    return context["plan_selection_data"]["downgradeLimits"][key]


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
