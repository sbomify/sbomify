"""The workspace names are canonical, and the team names still answer.

Branches written before the rename keep reversing ``teams:`` and reading
``settings.TEAMS_*`` until they re-run ``bin/rename_to_workspace.py``.
"""

from django.conf import settings
from django.urls import resolve, reverse


def test_the_role_settings_answer_to_both_names():
    assert settings.TEAMS_SUPPORTED_ROLES is settings.WORKSPACE_SUPPORTED_ROLES  # rename-to-workspace: keep
    assert settings.TEAMS_INVITABLE_ROLES is settings.WORKSPACE_INVITABLE_ROLES  # rename-to-workspace: keep


def test_a_workspace_page_resolves_under_the_workspaces_namespace():
    url = reverse("workspaces:team_settings_tab", kwargs={"team_key": "abc", "tab": "general"})

    assert url == "/workspaces/abc/settings/general"
    assert resolve(url).view_name == "workspaces:team_settings_tab"


def test_the_teams_namespace_still_reverses_to_the_same_page():
    kwargs = {"team_key": "abc", "tab": "general"}
    old = reverse("teams:team_settings_tab", kwargs=kwargs)  # rename-to-workspace: keep

    assert old == reverse("workspaces:team_settings_tab", kwargs=kwargs)


def test_the_singular_mount_still_serves_old_links():
    assert resolve("/workspace/abc/settings/general").view_name == "teams-legacy:team_settings_tab"
