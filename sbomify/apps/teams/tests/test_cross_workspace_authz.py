"""Being privileged in one workspace must not carry into another.

TeamRoleRequiredMixin authorizes against the workspace in the *session*, while
the handlers act on the workspace named in the *URL*. Those are not the same
thing, and `member` is the first non-guest role below ADMINISTER — get_team()
turns guests away, so before it existed this gap had no one to fall through it.
"""

import pytest
from django.urls import reverse

from sbomify.apps.teams.models import Member, Team


@pytest.fixture
def home(db):
    return Team.objects.create(name="Home Workspace")


@pytest.fixture
def other(db):
    return Team.objects.create(name="Other Workspace")


@pytest.fixture
def two_hatted_user(db, django_user_model, home, other):
    """Owner of one workspace, ordinary member of another."""
    user = django_user_model.objects.create_user(
        username="twohats", email="twohats@test.com", password="password"
    )
    Member.objects.create(user=user, team=home, role="owner", is_default_team=True)
    Member.objects.create(user=user, team=other, role="member", is_default_team=False)
    return user


def _session_for(client, team, role):
    session = client.session
    session["current_team"] = {"key": team.key, "name": team.name, "role": role, "id": team.id}
    session["user_teams"] = {team.key: {"role": role, "name": team.name}}
    session.save()


@pytest.mark.django_db
def test_owner_elsewhere_cannot_rename_a_workspace_they_are_only_a_member_of(client, two_hatted_user, home, other):
    client.force_login(two_hatted_user)
    _session_for(client, home, "owner")

    response = client.post(
        reverse("teams:team_general", kwargs={"team_key": other.key}),
        {"action": "update_name", "name": "Renamed By An Outsider"},
    )

    other.refresh_from_db()
    assert other.name == "Other Workspace", "a member renamed a workspace using their role in a different one"
    assert response.status_code in (403, 302)


@pytest.mark.django_db
def test_owner_elsewhere_cannot_change_another_workspaces_freshness_policy(client, two_hatted_user, home, other):
    client.force_login(two_hatted_user)
    _session_for(client, home, "owner")

    client.post(
        reverse("teams:team_general", kwargs={"team_key": other.key}),
        {"action": "update_name", "name": other.name, "sbom_freshness_days": 1},
    )

    other.refresh_from_db()
    assert other.sbom_freshness_days is None
