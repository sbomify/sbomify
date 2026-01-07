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
        role="member",
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
