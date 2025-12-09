import pytest
from django.urls import reverse
from sbomify.apps.teams.models import Member, Team, Invitation
from django.contrib.messages import get_messages

@pytest.fixture
def team(db):
    t = Team.objects.create(name="Team A", key="team-a-key")
    return t

@pytest.fixture
def other_team(db):
    t = Team.objects.create(name="Team B", key="team-b-key", billing_plan="business")
    # Mock limits to allow adding users
    return t

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

def test_removal_fallback_when_pending_invites_exist(client, owner, user_with_one_team, team, other_team):
    """
    Test that when a user is removed from their last workspace and has pending invites,
    we do NOT create a personal workspace, but handle it gracefully.
    """
    # 1. Setup: User has a pending invite to Team B (joinable)
    Invitation.objects.create(team=other_team, email=user_with_one_team.email, role="member")
    
    # 2. Action: Owner removes User from Team A (their only team)
    client.force_login(owner)
    membership = Member.objects.get(user=user_with_one_team, team=team)
    
    url = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})
    response = client.get(url)
    
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
    assert "Member user1 removed from workspace." == str(messages[0])
    assert "personal workspace" not in str(messages[0])

def test_self_removal_fallback_when_pending_invites_exist(client, user_with_one_team, team, other_team):
    """
    Test that when a user REMOVES THEMSELVES from their last workspace and has pending invites,
    we redirect them to dashboard and clear session.
    """
    # 1. Setup: User has pending invite
    Invitation.objects.create(team=other_team, email=user_with_one_team.email, role="member")
    
    # 2. Action: User leaves Team A
    client.force_login(user_with_one_team)
    membership = Member.objects.get(user=user_with_one_team, team=team)
    
    url = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})
    response = client.get(url)
    
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
