import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0033_release_lifecycle"),
        ("sboms", "0068_rename_sboms_compo_team_id_fe2066_idx_sboms_compo_workspa_3edbe9_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="releasecleevent",
            name="drop_in",
            field=models.BooleanField(
                default=False,
                help_text="Whether the successor replaces this release, so this release stops being monitored",
            ),
        ),
        migrations.AddField(
            model_name="releasecleevent",
            name="superseded_by_release",
            field=models.ForeignKey(
                blank=True,
                help_text="The release in the same product that superseded_by_version resolved to, if any",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="supersedes_events",
                to="core.release",
            ),
        ),
    ]
