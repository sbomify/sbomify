from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0068_rename_sboms_compo_team_id_fe2066_idx_sboms_compo_workspa_3edbe9_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="component",
            name="vcs_url",
            field=models.URLField(
                blank=True,
                default="",
                help_text="Source control repository the component is built from",
                max_length=500,
            ),
        ),
    ]
