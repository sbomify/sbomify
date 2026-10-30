import django.db.models.deletion
import sbomify.apps.core.utils
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0033_release_links"),
        ("sboms", "0068_rename_sboms_compo_team_id_fe2066_idx_sboms_compo_workspa_3edbe9_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="release",
            name="archived_at",
            field=models.DateTimeField(blank=True, help_text="When the release was archived", null=True),
        ),
        migrations.AddField(
            model_name="release",
            name="end_of_life",
            field=models.DateField(blank=True, help_text="End of life, derived from CLE events", null=True),
        ),
        migrations.AddField(
            model_name="release",
            name="effective_end_of_life",
            field=models.DateField(
                blank=True, help_text="End of life that applies: the release's own, else the product's", null=True
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="effective_end_of_support",
            field=models.DateField(
                blank=True, help_text="End of support that applies: the release's own, else the product's", null=True
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="end_of_support",
            field=models.DateField(
                blank=True, help_text="Final end of support across support policies, derived from CLE events", null=True
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="superseded_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the earliest drop-in successor took over, derived from CLE events",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="release",
            name="withdrawn_at",
            field=models.DateTimeField(blank=True, help_text="When the release was withdrawn", null=True),
        ),
        migrations.AddField(
            model_name="release",
            name="withdrawn_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("defective", "Defective"),
                    ("compromised", "Compromised"),
                    ("published_in_error", "Published in error"),
                ],
                default="",
                help_text="Why the release was withdrawn",
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="ReleaseSupersession",
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
                ("successor_label", models.CharField(help_text="The successor's version as asserted", max_length=255)),
                (
                    "drop_in",
                    models.BooleanField(
                        default=False,
                        help_text="Whether the successor replaces this release, so this release stops being monitored",
                    ),
                ),
                ("reason", models.TextField(blank=True, default="")),
                ("effective", models.DateTimeField(help_text="When the successor takes over")),
                (
                    "withdrawn_at",
                    models.DateTimeField(
                        blank=True, help_text="When the edge was withdrawn; empty while live", null=True
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "cle_event",
                    models.OneToOneField(
                        blank=True,
                        help_text="The supersededBy CLE event this edge is published as",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="supersession",
                        to="sboms.releasecleevent",
                    ),
                ),
                (
                    "from_release",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="successor_edges", to="core.release"
                    ),
                ),
                (
                    "to_release",
                    models.ForeignKey(
                        blank=True,
                        help_text="The successor in the same product, if sbomify has it",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="predecessor_edges",
                        to="core.release",
                    ),
                ),
            ],
            options={
                "db_table": "core_release_supersessions",
                "ordering": ["created_at"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("from_release", models.F("to_release")), _negated=True),
                        name="release_supersession_not_self",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("withdrawn_at__isnull", True)),
                        fields=("from_release", "successor_label"),
                        name="unique_live_release_supersession",
                    ),
                ],
            },
        ),
    ]
