from django.db import migrations


def publish_active_catalogs(apps, schema_editor):
    """Keep on the public side whatever was already on it.

    Before ``is_published`` existed, ``is_active`` was the switch: the public
    controls endpoints and the public product page both read it, and
    ``deactivate_catalog`` is documented as hiding a catalog from the trust
    center. Defaulting the new flag to false therefore does not leave those
    workspaces where they were, it takes their published frameworks down.

    Only frameworks a workspace maintains itself are covered. A synced one
    opts in through the Integrations tab, which is the decision this flag was
    added for, and no synced catalog exists yet when this runs.
    """
    ControlCatalog = apps.get_model("controls", "ControlCatalog")
    ControlCatalog.objects.filter(is_active=True, is_published=False).exclude(source="vanta").update(is_published=True)


class Migration(migrations.Migration):
    dependencies = [
        ("controls", "0008_controlcatalog_unique_catalog_per_external_id"),
    ]

    operations = [
        migrations.RunPython(publish_active_catalogs, migrations.RunPython.noop),
    ]
