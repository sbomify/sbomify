"""The workspace names are the only names.

The team names answered for a while after the rename. A branch that still uses
one fails here, and ``bin/rename_to_workspace.py`` rewrites it.
"""

import ast
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import NoReverseMatch, resolve, reverse


def test_the_role_settings_have_only_the_workspace_names():
    assert settings.WORKSPACE_SUPPORTED_ROLES
    assert not hasattr(settings, "TEAMS_SUPPORTED_ROLES")  # rename-to-workspace: keep
    assert not hasattr(settings, "TEAMS_INVITABLE_ROLES")  # rename-to-workspace: keep


def test_the_screencasts_import_no_team_name():
    """pytest never collects ``screencasts/``, so an old name there breaks only a recording."""
    imported: set[str] = set()
    for path in (Path(settings.BASE_DIR) / "screencasts").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "sbomify.apps.teams.models":
                imported |= {alias.name for alias in node.names}

    assert imported, "no screencast imports the teams models, so this test checks nothing"
    assert "Team" not in imported  # rename-to-workspace: keep


def test_a_workspace_page_resolves_under_the_workspaces_namespace():
    url = reverse("workspaces:team_settings_tab", kwargs={"workspace_key": "abc", "tab": "general"})

    assert url == "/workspaces/abc/settings/general"
    assert resolve(url).view_name == "workspaces:team_settings_tab"


def test_the_teams_namespace_is_gone():
    kwargs = {"workspace_key": "abc", "tab": "general"}
    with pytest.raises(NoReverseMatch):
        reverse("teams:team_settings_tab", kwargs=kwargs)  # rename-to-workspace: keep


def test_the_singular_mount_still_serves_old_links():
    assert resolve("/workspace/abc/settings/general").view_name == "teams-legacy:team_settings_tab"


def test_the_workspace_model_has_no_team_alias():
    from sbomify.apps.teams import models
    from sbomify.apps.teams.models import Workspace

    assert not hasattr(models, "Team")  # rename-to-workspace: keep
    assert Workspace._meta.label == "teams.Workspace"
    assert Workspace._meta.db_table == "workspaces_workspaces"


@pytest.mark.django_db
def test_a_user_reaches_their_workspaces_by_the_old_reverse_names(sample_team_with_owner_member):
    from django.contrib.auth import get_user_model

    member = sample_team_with_owner_member

    assert list(member.user.team_set.all()) == [member.team]
    assert get_user_model().objects.filter(team=member.team).get() == member.user


def _rename_permissions(direction="rename_to_workspace"):
    import importlib

    from django.apps import apps

    module = importlib.import_module("sbomify.apps.teams.migrations.0049_rename_team_permissions")
    getattr(module, direction)(apps, None)


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
@pytest.mark.parametrize(
    ("direction", "old", "new"),
    [
        ("rename_to_workspace", "team", "workspace"),  # rename-to-workspace: keep
        ("rename_to_team", "workspace", "team"),  # rename-to-workspace: keep
    ],
)
def test_grants_move_onto_a_permission_that_already_exists(sample_user, direction, old, new):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group, Permission
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get(app_label="teams", model="workspace")
    Permission.objects.filter(content_type=content_type, codename__startswith="change_").delete()
    stale = Permission.objects.create(content_type=content_type, codename=f"change_{old}", name=f"Can change {old}")
    target = Permission.objects.create(content_type=content_type, codename=f"change_{new}", name=f"Can change {new}")
    group = Group.objects.create(name="workspace editors")
    sample_user.user_permissions.add(stale)
    group.permissions.add(stale)

    _rename_permissions(direction)

    assert not Permission.objects.filter(pk=stale.pk).exists()
    assert Permission.objects.filter(content_type=content_type, codename=f"change_{new}").count() == 1
    assert get_user_model().objects.get(pk=sample_user.pk).has_perm(f"teams.change_{new}")
    assert list(group.permissions.all()) == [target]
