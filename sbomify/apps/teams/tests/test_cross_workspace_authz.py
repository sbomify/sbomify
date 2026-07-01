"""Cross-workspace authorization: actions must be authorized against the TARGET workspace,
not the actor's session workspace."""

import pytest
from django.urls import reverse

from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Invitation, Member, Team


@pytest.fixture
def attacker(db, django_user_model):
    """Owns their own workspace A; not a member of anyone else's."""
    user = django_user_model.objects.create_user(username="attacker", email="attacker@evil.test", password="pw")
    team_a = Team.objects.create(name="Attacker WS")
    team_a.key = number_to_random_token(team_a.pk)
    team_a.save()
    Member.objects.create(user=user, team=team_a, role="owner", is_default_team=True)
    return user, team_a


@pytest.fixture
def victim_team(db, django_user_model):
    """A separate tenant's workspace with an owner; the attacker is NOT a member."""
    owner = django_user_model.objects.create_user(username="victim", email="victim@corp.test", password="pw")
    team_b = Team.objects.create(name="Victim WS")
    team_b.key = number_to_random_token(team_b.pk)
    team_b.save()
    Member.objects.create(user=owner, team=team_b, role="owner", is_default_team=True)
    return team_b, owner


def _session_as(client, team, role):
    session = client.session
    session["current_team"] = {"key": team.key, "name": team.name, "role": role}
    session["user_teams"] = {team.key: {"role": role, "name": team.name}}
    session.save()


@pytest.mark.django_db
def test_cannot_invite_into_another_workspace(client, attacker, victim_team):
    """Owning workspace A must not let you invite (as owner) into workspace B."""
    user, team_a = attacker
    team_b, _ = victim_team
    client.force_login(user)
    _session_as(client, team_a, "owner")

    resp = client.post(
        reverse("teams:invite_user", kwargs={"team_key": team_b.key}),
        {"email": "attacker@evil.test", "role": "owner"},
    )

    assert resp.status_code == 403
    assert not Invitation.objects.filter(team=team_b).exists()


@pytest.mark.django_db
def test_cannot_delete_member_in_another_workspace(client, attacker, victim_team):
    """Must not delete a membership belonging to a workspace you don't administer."""
    user, team_a = attacker
    team_b, victim_owner = victim_team
    target = Member.objects.get(team=team_b, user=victim_owner)
    client.force_login(user)
    _session_as(client, team_a, "owner")

    resp = client.delete(reverse("teams:team_membership_delete", kwargs={"membership_id": target.id}))

    assert resp.status_code == 403
    assert Member.objects.filter(pk=target.pk).exists()


@pytest.mark.django_db
def test_cannot_delete_invite_in_another_workspace(client, attacker, victim_team):
    """Must not delete a pending invitation belonging to another workspace."""
    user, team_a = attacker
    team_b, _ = victim_team
    invite = Invitation.objects.create(email="pending@corp.test", team=team_b, role="admin")
    client.force_login(user)
    _session_as(client, team_a, "owner")

    resp = client.delete(reverse("teams:team_invitation_delete", kwargs={"invitation_id": invite.id}))

    assert resp.status_code == 403
    assert Invitation.objects.filter(pk=invite.pk).exists()
