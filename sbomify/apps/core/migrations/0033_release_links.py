"""A release can link to another product's release."""

import django.db.models.deletion
import sbomify.apps.core.utils
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_drop_document_revision_vex_pins"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReleaseLink",
            fields=[
                (
                    "id",
                    models.CharField(
                        default=sbomify.apps.core.utils.generate_id,
                        editable=False,
                        max_length=20,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "linked_release",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="linked_from", to="core.release"
                    ),
                ),
                (
                    "release",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="links", to="core.release"
                    ),
                ),
            ],
            options={
                "db_table": "core_release_links",
                "ordering": ["created_at"],
                "constraints": [
                    models.UniqueConstraint(fields=("release", "linked_release"), name="unique_release_link"),
                    models.CheckConstraint(
                        condition=models.Q(("release", models.F("linked_release")), _negated=True),
                        name="release_link_not_self",
                    ),
                ],
            },
        ),
    ]
