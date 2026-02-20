from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plugins", "0004_migrate_osv_results_to_assessment_runs"),
    ]

    operations = [
        migrations.AddField(
            model_name="registeredplugin",
            name="config_schema",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Schema defining configurable fields for this plugin",
            ),
        ),
    ]
