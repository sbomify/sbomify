import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import sbomify.apps.core.utils


class Migration(migrations.Migration):
    dependencies = [
        ("controls", "0003_add_control_mapping"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ControlEvidence",
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
                    "evidence_type",
                    models.CharField(
                        choices=[
                            ("document", "Document"),
                            ("url", "URL"),
                            ("note", "Note"),
                        ],
                        max_length=20,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("url", models.URLField(blank=True, default="")),
                ("document_id", models.CharField(blank=True, default="", max_length=20)),
                ("description", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "control_status",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="evidence",
                        to="controls.controlstatus",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "controls_evidence",
                "ordering": ["-created_at"],
            },
        ),
    ]
