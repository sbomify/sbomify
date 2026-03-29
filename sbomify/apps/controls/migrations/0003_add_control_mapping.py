import django.db.models.deletion
from django.db import migrations, models

import sbomify.apps.core.utils


class Migration(migrations.Migration):
    dependencies = [
        ("controls", "0002_add_status_log"),
    ]

    operations = [
        migrations.CreateModel(
            name="ControlMapping",
            fields=[
                (
                    "id",
                    models.CharField(
                        default=sbomify.apps.core.utils.generate_id,
                        max_length=20,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "relation_type",
                    models.CharField(
                        choices=[
                            ("equivalent", "Equivalent"),
                            ("partial", "Partial Overlap"),
                            ("related", "Related"),
                        ],
                        max_length=20,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "source_control",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mappings_as_source",
                        to="controls.control",
                    ),
                ),
                (
                    "target_control",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mappings_as_target",
                        to="controls.control",
                    ),
                ),
            ],
            options={
                "db_table": "controls_mapping",
                "unique_together": {("source_control", "target_control")},
            },
        ),
    ]
