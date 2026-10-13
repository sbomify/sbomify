from django.db import migrations

ACTIONS = ("add", "change", "delete", "view")


def _rename(apps, old, new):
    """Rename the model's default permissions, which the content type rename leaves behind.

    Renaming in place keeps every grant attached. A fresh database has no
    content type yet, so there is nothing to do; a codename that already exists
    under the new name is left alone rather than duplicated.
    """
    content_type = apps.get_model("contenttypes", "ContentType").objects.filter(app_label="teams", model="workspace")
    permission = apps.get_model("auth", "Permission")
    for action in ACTIONS:
        if permission.objects.filter(content_type__in=content_type, codename=f"{action}_{new}").exists():
            continue
        permission.objects.filter(content_type__in=content_type, codename=f"{action}_{old}").update(
            codename=f"{action}_{new}", name=f"Can {action} {new}"
        )


def rename_to_workspace(apps, schema_editor):
    _rename(apps, "team", "workspace")  # rename-to-workspace: keep


def rename_to_team(apps, schema_editor):
    _rename(apps, "workspace", "team")  # rename-to-workspace: keep


class Migration(migrations.Migration):
    dependencies = [
        ("teams", "0048_rename_team_workspace"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(rename_to_workspace, rename_to_team)]
