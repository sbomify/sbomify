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

    assert Team is Workspace  # rename-to-workspace: keep
    assert Workspace._meta.label == "teams.Workspace"
    assert Workspace._meta.db_table == "workspaces_workspaces"


@pytest.mark.django_db
def test_a_user_reaches_their_workspaces_by_the_old_reverse_names(sample_team_with_owner_member):
    from django.contrib.auth import get_user_model

    member = sample_team_with_owner_member

    assert list(member.user.team_set.all()) == [member.team]
    assert get_user_model().objects.filter(team=member.team).get() == member.user


def _rename_permissions():
    import importlib

    from django.apps import apps

    module = importlib.import_module("sbomify.apps.teams.migrations.0049_rename_team_permissions")
    module.rename_to_workspace(apps, None)


@pytest.mark.django_db
def test_a_grant_on_the_old_permission_survives_the_rename(sample_user):
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get(app_label="teams", model="workspace")
    # The state an existing database is in after 0048: the content type is
    # renamed, its permissions still carry the old codenames.
    Permission.objects.filter(content_type=content_type).delete()
    for action in ("add", "change", "delete", "view"):
        Permission.objects.create(
            content_type=content_type,
            codename=f"{action}_team",  # rename-to-workspace: keep
            name=f"Can {action} team",  # rename-to-workspace: keep
        )
    sample_user.user_permissions.add(Permission.objects.get(codename="change_team"))  # rename-to-workspace: keep

    _rename_permissions()

    codenames = set(Permission.objects.filter(content_type=content_type).values_list("codename", "name"))
    assert codenames == {(f"{a}_workspace", f"Can {a} workspace") for a in ("add", "change", "delete", "view")}
    sample_user.refresh_from_db()
    assert sample_user.has_perm("teams.change_workspace")


@pytest.mark.django_db
def test_the_rename_leaves_a_workspace_permission_that_already_exists():
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get(app_label="teams", model="workspace")
    old = Permission.objects.create(
        content_type=content_type,
        codename="change_team",  # rename-to-workspace: keep
        name="Can change team",  # rename-to-workspace: keep
    )

    _rename_permissions()

    assert Permission.objects.filter(content_type=content_type, codename="change_workspace").count() == 1
    assert Permission.objects.filter(pk=old.pk, codename="change_team").exists()  # rename-to-workspace: keep
