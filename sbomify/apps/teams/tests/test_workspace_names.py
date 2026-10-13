"""The workspace names are canonical, and the team names still answer.

Branches written before the rename keep reversing ``teams:`` and reading
``settings.TEAMS_*`` until they re-run ``bin/rename_to_workspace.py``.
"""

import pytest
from django.conf import settings
from django.urls import resolve, reverse


def test_the_role_settings_answer_to_both_names():
    assert settings.TEAMS_SUPPORTED_ROLES is settings.WORKSPACE_SUPPORTED_ROLES  # rename-to-workspace: keep
    assert settings.TEAMS_INVITABLE_ROLES is settings.WORKSPACE_INVITABLE_ROLES  # rename-to-workspace: keep


def test_a_workspace_page_resolves_under_the_workspaces_namespace():
    url = reverse("workspaces:team_settings_tab", kwargs={"workspace_key": "abc", "tab": "general"})

    assert url == "/workspaces/abc/settings/general"
    assert resolve(url).view_name == "workspaces:team_settings_tab"


def test_the_teams_namespace_still_reverses_to_the_same_page():
    kwargs = {"workspace_key": "abc", "tab": "general"}
    old = reverse("teams:team_settings_tab", kwargs=kwargs)  # rename-to-workspace: keep

    assert old == reverse("workspaces:team_settings_tab", kwargs=kwargs)


def test_the_singular_mount_still_serves_old_links():
    assert resolve("/workspace/abc/settings/general").view_name == "teams-legacy:team_settings_tab"


def test_the_team_model_name_still_imports_as_the_workspace_model():
    from sbomify.apps.teams.models import Team, Workspace  # rename-to-workspace: keep

    assert Team is Workspace
    assert Workspace._meta.label == "teams.Workspace"
    assert Workspace._meta.db_table == "workspaces_workspaces"


@pytest.mark.django_db
def test_a_user_reaches_their_workspaces_by_the_old_reverse_names(sample_team_with_owner_member):
    from django.contrib.auth import get_user_model

    member = sample_team_with_owner_member

    assert list(member.user.team_set.all()) == [member.team]
    assert get_user_model().objects.filter(team=member.team).get() == member.user
