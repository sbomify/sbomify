import pytest
from django.urls import reverse
from sbomify.apps.teams.models import Member, Team

@pytest.fixture
def team(db):
    t = Team.objects.create(name="Test Team", key="testteamkey")
    return t

@pytest.fixture
def owner(db, django_user_model, team):
    u = django_user_model.objects.create_user(username="owner", email="owner@test.com", password="password")
    Member.objects.create(user=u, team=team, role="owner", is_default_team=True)
    return u

@pytest.fixture
def admin_user(db, django_user_model, team):
    u = django_user_model.objects.create_user(username="admin", email="admin@test.com", password="password")
    Member.objects.create(user=u, team=team, role="admin", is_default_team=True)
    return u

@pytest.fixture
def member_user(db, django_user_model, team):
    u = django_user_model.objects.create_user(username="member", email="member@test.com", password="password")
    Member.objects.create(user=u, team=team, role="member", is_default_team=True)
    return u

@pytest.fixture
def another_owner(db, django_user_model, team):
    u = django_user_model.objects.create_user(username="owner2", email="owner2@test.com", password="password")
    Member.objects.create(user=u, team=team, role="owner", is_default_team=False)
    return u

def test_admin_can_remove_member(client, admin_user, member_user, team):
    client.force_login(admin_user)
    membership = Member.objects.get(user=member_user, team=team)
    
    # Test POST to team settings endpoint
    url = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(url, {"_method": "DELETE", "member_id": membership.id})
    
    assert response.status_code == 302
    assert not Member.objects.filter(pk=membership.pk).exists()

def test_admin_cannot_remove_owner(client, admin_user, owner, team):
    client.force_login(admin_user)
    membership = Member.objects.get(user=owner, team=team)
    
    # Test POST to team settings endpoint
    url = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(url, {"_method": "DELETE", "member_id": membership.id})
    
    # Should redirect and NOT delete
    assert response.status_code == 302
    assert Member.objects.filter(pk=membership.pk).exists()
    
    messages = list(response.wsgi_request._messages)
    assert len(messages) > 0
    assert "Admins cannot remove workspace owners" in str(messages[0])

def test_owner_can_remove_admin(client, owner, admin_user, team):
    client.force_login(owner)
    membership = Member.objects.get(user=admin_user, team=team)
    
    url = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(url, {"_method": "DELETE", "member_id": membership.id})
    
    assert response.status_code == 302
    assert not Member.objects.filter(pk=membership.pk).exists()

def test_admin_access_to_delete_member_view(client, admin_user, member_user, team):
    # Test the direct view access as well (GET/direct call usually via HTMX or link)
    # Note: the delete_member view takes membership_id
    client.force_login(admin_user)
    membership = Member.objects.get(user=member_user, team=team)
    
    url = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})
    response = client.get(url) 
    
    assert response.status_code == 302
    assert not Member.objects.filter(pk=membership.pk).exists()

def test_admin_cannot_access_delete_owner_via_direct_view(client, admin_user, owner, team):
    client.force_login(admin_user)
    membership = Member.objects.get(user=owner, team=team)
    
    url = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})
    response = client.get(url)
    
    assert response.status_code == 302
    assert Member.objects.filter(pk=membership.pk).exists()
