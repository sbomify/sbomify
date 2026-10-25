# Changes an AI agent sends for a published advisory wait here for a person,
# and an edited timeline message is recorded as its own event.

import django.db.models.deletion
import sbomify.apps.core.utils
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("access_tokens", "0012_store_token_hash"),
        ("security_advisories", "0009_csaf_document_revision"),
        ("teams", "0050_workspace_advisory_id_settings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="advisoryevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("comment", "Comment"),
                    ("update", "Update"),
                    ("field_change", "Field change"),
                    ("status_change", "Status change"),
                    ("visibility_changed", "Visibility changed"),
                    ("published", "Published"),
                    ("withdrawn", "Withdrawn"),
                    ("vulnerability_added", "Vulnerability added"),
                    ("vulnerability_removed", "Vulnerability removed"),
                    ("product_added", "Product added"),
                    ("product_removed", "Product removed"),
                    ("cra_early_warning", "CRA early warning submitted"),
                    ("cra_notification", "CRA notification submitted"),
                    ("cra_final_report", "CRA final report submitted"),
                    ("users_notified", "Impacted users notified"),
                    ("message_edited", "Message edited"),
                ],
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="AdvisoryProposal",
            fields=[
                (
                    "id",
                    models.CharField(
                        default=sbomify.apps.core.utils.generate_id, max_length=20, primary_key=True, serialize=False
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("post_update", "New update"),
                            ("edit_update", "Edit to an update"),
                            ("edit_advisory", "Edit to the advisory"),
                            ("product_status", "Product status change"),
                            ("add_product", "Product added"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Awaiting review"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("superseded", "Replaced"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("target", models.CharField(blank=True, default="", max_length=255)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("baseline", models.JSONField(blank=True, default=dict)),
                ("context", models.TextField(blank=True, default="")),
                ("channel", models.CharField(default="agent", max_length=10)),
                ("submitted_token_description", models.CharField(blank=True, default="", max_length=255)),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.TextField(blank=True, default="")),
                ("revised", models.BooleanField(default=False)),
                (
                    "advisory",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="proposals",
                        to="security_advisories.securityadvisory",
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "submitted_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="advisory_proposals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "submitted_token",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="access_tokens.accesstoken",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_column="workspace_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="advisory_proposals",
                        to="teams.workspace",
                    ),
                ),
            ],
            options={
                "db_table": "security_advisories_proposals",
                "ordering": ["-submitted_at"],
                "indexes": [
                    models.Index(fields=["team", "status"], name="sec_adv_prop_team_status_idx"),
                    models.Index(fields=["advisory", "status"], name="sec_adv_prop_adv_status_idx"),
                ],
            },
        ),
    ]
