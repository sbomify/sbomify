# Generated manually for gated documents feature

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import sbomify.apps.core.utils


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0006_add_nda_and_subcategories"),
        ("teams", "0023_member_team_role_index"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccessRequest",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("revoked", "Revoked"),
                        ],
                        default="pending",
                        help_text="Status of the access request",
                        max_length=20,
                    ),
                ),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                (
                    "decided_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the request was approved or rejected",
                        null=True,
                    ),
                ),
                (
                    "revoked_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the access was revoked",
                        null=True,
                    ),
                ),
                (
                    "notes",
                    models.TextField(
                        blank=True,
                        help_text="Optional notes about the request",
                        max_length=1000,
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="decided_access_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "revoked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="revoked_access_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_requests",
                        to="teams.team",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "documents_access_requests",
                "ordering": ["-requested_at"],
            },
        ),
        migrations.CreateModel(
            name="NDASignature",
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
                    "nda_content_hash",
                    models.CharField(
                        help_text="SHA-256 hash of NDA document content at signing time",
                        max_length=64,
                    ),
                ),
                (
                    "signed_name",
                    models.CharField(
                        help_text="Name provided by user when signing",
                        max_length=255,
                    ),
                ),
                (
                    "signed_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When the NDA was signed",
                    ),
                ),
                (
                    "ip_address",
                    models.GenericIPAddressField(
                        blank=True,
                        help_text="IP address of user when signing",
                        null=True,
                    ),
                ),
                (
                    "user_agent",
                    models.CharField(
                        blank=True,
                        help_text="User agent string of browser when signing",
                        max_length=500,
                    ),
                ),
                (
                    "access_request",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="nda_signature",
                        to="documents.accessrequest",
                    ),
                ),
                (
                    "nda_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="nda_signatures",
                        to="documents.document",
                    ),
                ),
            ],
            options={
                "db_table": "documents_nda_signatures",
                "ordering": ["-signed_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="accessrequest",
            constraint=models.UniqueConstraint(
                fields=("team", "user"),
                name="documents_access_requests_team_user_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="accessrequest",
            index=models.Index(
                fields=["team", "user", "status"],
                name="documents_a_team_id_838fe2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="accessrequest",
            index=models.Index(
                fields=["status"],
                name="documents_a_status_071820_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="accessrequest",
            index=models.Index(
                fields=["requested_at"],
                name="documents_a_request_5b0521_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="ndasignature",
            index=models.Index(
                fields=["access_request"],
                name="documents_n_access__14ea9a_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="ndasignature",
            index=models.Index(
                fields=["signed_at"],
                name="documents_n_signed__04d7df_idx",
            ),
        ),
    ]
