import pytest
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.utils import can_add_user_to_team


@pytest.mark.django_db
def test_invite_limit_counts_pending_invitations(django_user_model):
    """Test that pending invitations count towards the user limit."""
    
    # 1. Setup team and plan with max_users=2
    BillingPlan.objects.create(
        key="community",
        name="Community",
        description="Community Plan",
        max_users=2
    )
    
    user1 = django_user_model.objects.create_user(username="owner", email="owner@example.com", password="password")
    team = Team.objects.create(name="Test Team", billing_plan="community")
    Member.objects.create(user=user1, team=team, role="owner")
    
    # 2. Verify team has 1 member
    assert Member.objects.filter(team=team).count() == 1
    
    # Check limit - should allow adding 1 more
    can_add, _ = can_add_user_to_team(team)
    assert can_add is True
    
    # 3. Send 1 valid invitation (simulate by creating object)
    Invitation.objects.create(
        team=team,
        email="invitee@example.com",
        role="admin",
        expires_at=timezone.now() + timezone.timedelta(days=7)
    )
    
    # 4. Attempt to send a 2nd invitation (Should fail: 1 member + 1 pending = 2 >= 2)
    can_add, msg = can_add_user_to_team(team)
    assert can_add is False
    assert "Community plan allows only 2 users" in msg
    
    # 5. Expire the 1st invitation
    Invitation.objects.update(expires_at=timezone.now() - timezone.timedelta(days=1))
    
    # 6. Attempt to send the 2nd invitation again (Should succeed: 1 member + 0 pending = 1 < 2)
    can_add, _ = can_add_user_to_team(team)
    assert can_add is True


@pytest.mark.django_db
def test_a_scheduled_downgrade_caps_seats_at_the_plan_it_drops_to(django_user_model, mocker):
    """Products and components already stop at the plan a cancelled subscription
    drops to. Seats stop there too, so the downgrade cannot land over its limit."""
    still_cancelling = mocker.patch(
        "sbomify.apps.teams.utils.get_subscription_cancel_at_period_end", return_value=True
    )
    BillingPlan.objects.create(key="community", name="Community", max_users=1)
    BillingPlan.objects.create(key="business", name="Business", max_users=10)
    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com", password="password")
    team = Team.objects.create(
        name="Downgrading Team",
        billing_plan="business",
        billing_plan_limits={
            "cancel_at_period_end": True,
            "scheduled_downgrade_plan": "community",
            "stripe_subscription_id": "sub_test",
            "stripe_customer_id": "cus_test",
        },
    )
    Member.objects.create(user=owner, team=team, role="owner")

    can_add, msg = can_add_user_to_team(team)
    assert can_add is False
    assert "scheduled downgrade to Community" in msg
    assert "the plan limit of 1 member." in msg

    # Reactivated in Stripe before the webhook landed: the paid plan decides again.
    still_cancelling.return_value = False
    assert can_add_user_to_team(team) == (True, "")
