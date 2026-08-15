from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.teams.models import Invitation, Member, Team


@pytest.fixture
def team(db):
    return Team.objects.create(name="Test Team", key="testteamkey")


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


def _setup_session(client, team, role):
    """Helper to set up session data for a user after force_login."""
    session = client.session
    session["current_team"] = {"key": team.key, "name": team.name, "role": role}
    session["user_teams"] = {team.key: {"role": role, "name": team.name}}
    session.save()


def test_admin_can_remove_member(client, admin_user, member_user, team):
    client.force_login(admin_user)
    _setup_session(client, team, "admin")
    membership = Member.objects.get(user=member_user, team=team)

    # Test POST to team settings endpoint
    url = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(url, {"_method": "DELETE", "member_id": membership.id})

    assert response.status_code == 302
    assert not Member.objects.filter(pk=membership.pk).exists()


def test_admin_cannot_remove_owner(client, admin_user, owner, team):
    client.force_login(admin_user)
    _setup_session(client, team, "admin")
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


def test_settings_for_a_workspace_you_do_not_belong_to_is_refused(client, owner, django_user_model):
    """The mixin authorizes the *session* workspace; the view renders the URL one.

    So an owner of A can reach B's settings URL past the mixin. The view
    re-resolves the role against B and refuses — this pins that, and that the
    refusal says the right thing rather than blaming the user's role.
    """
    # No explicit key: Team.save() derives a real token from the pk, and the
    # settings path decodes it. A hand-written key decodes to nothing and 404s
    # before any of the logic under test runs.
    other = Team.objects.create(name="Someone Else's Workspace")
    stranger = django_user_model.objects.create_user(
        username="stranger", email="stranger@test.com", password="password"
    )
    Member.objects.create(user=stranger, team=other, role="owner", is_default_team=True)

    client.force_login(owner)
    _setup_session(client, Team.objects.get(key="testteamkey"), "owner")

    response = client.get(reverse("teams:team_settings", kwargs={"team_key": other.key}))

    assert response.status_code == 403


def test_an_expired_invitation_does_not_unlock_admin_self_removal(client, admin_user, team, django_user_model):
    """The self-removal exception is for admins actually leaving for somewhere.

    The check was exists() over every Invitation ever addressed to them — under
    a variable named has_pending_invites — so an invitation that lapsed months
    ago still bought a way past the rule.
    """
    Invitation.objects.create(
        team=Team.objects.create(name="Somewhere Else"),
        email=admin_user.email,
        role="member",
        expires_at=timezone.now() - timedelta(days=30),
    )

    client.force_login(admin_user)
    _setup_session(client, team, "admin")
    membership = Member.objects.get(user=admin_user, team=team)

    url = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(url, {"_method": "DELETE", "member_id": membership.id})

    assert response.status_code == 403
    assert Member.objects.filter(pk=membership.pk).exists()


def test_a_live_invitation_still_unlocks_admin_self_removal(client, admin_user, team):
    """The exception itself must keep working — an admin leaving can still go."""
    Invitation.objects.create(
        team=Team.objects.create(name="Somewhere Else"),
        email=admin_user.email,
        role="member",
        expires_at=timezone.now() + timedelta(days=7),
    )

    client.force_login(admin_user)
    _setup_session(client, team, "admin")
    membership = Member.objects.get(user=admin_user, team=team)

    url = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(url, {"_method": "DELETE", "member_id": membership.id})

    assert response.status_code == 302
    assert not Member.objects.filter(pk=membership.pk).exists()


def test_settings_tab_answers_403_for_an_authorization_refusal(client, admin_user, team):
    """The members tab must not downgrade a 403 to a redirect.

    check_member_removal marks the admin self-removal rule ``forbidden`` — an
    authorization refusal, not advice the user can act on. Both removal paths
    are plain form posts, so answering it differently in the settings tab is
    drift of exactly the kind the shared helper exists to prevent.
    """
    client.force_login(admin_user)
    _setup_session(client, team, "admin")
    membership = Member.objects.get(user=admin_user, team=team)

    url = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(url, {"_method": "DELETE", "member_id": membership.id})

    assert response.status_code == 403
    assert Member.objects.filter(pk=membership.pk).exists()


def test_settings_tab_still_redirects_for_an_advisory_refusal(client, owner, team):
    """The last-owner rule is advisory, so it keeps the message-and-redirect shape."""
    client.force_login(owner)
    _setup_session(client, team, "owner")
    membership = Member.objects.get(user=owner, team=team)

    url = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(url, {"_method": "DELETE", "member_id": membership.id})

    assert response.status_code == 302
    assert Member.objects.filter(pk=membership.pk).exists()
    messages = list(response.wsgi_request._messages)
    assert "assign another owner first" in str(messages[0]).lower()


def test_owner_can_remove_admin(client, owner, admin_user, team):
    client.force_login(owner)
    _setup_session(client, team, "owner")
    membership = Member.objects.get(user=admin_user, team=team)

    url = reverse("teams:team_settings", kwargs={"team_key": team.key})
    response = client.post(url, {"_method": "DELETE", "member_id": membership.id})

    assert response.status_code == 302
    assert not Member.objects.filter(pk=membership.pk).exists()


def test_admin_access_to_delete_member_view(client, admin_user, member_user, team):
    # Test the direct view access as well (GET/direct call usually via HTMX or link)
    # Note: the delete_member view takes membership_id
    client.force_login(admin_user)
    _setup_session(client, team, "admin")
    membership = Member.objects.get(user=member_user, team=team)

    url = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})
    response = client.delete(url)

    assert response.status_code == 302
    assert not Member.objects.filter(pk=membership.pk).exists()


def test_admin_cannot_access_delete_owner_via_direct_view(client, admin_user, owner, team):
    client.force_login(admin_user)
    _setup_session(client, team, "admin")
    membership = Member.objects.get(user=owner, team=team)

    url = reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id})
    response = client.delete(url)

    assert response.status_code == 302
    assert Member.objects.filter(pk=membership.pk).exists()
