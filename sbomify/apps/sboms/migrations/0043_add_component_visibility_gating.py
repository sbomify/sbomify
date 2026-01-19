# Generated manually for gated documents feature

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0042_remove_productlink_unique_constraint"),
        ("documents", "0005_document_documents_d_created_bd50af_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="component",
            name="visibility",
            field=models.CharField(
                choices=[("public", "Public"), ("private", "Private"), ("gated", "Gated")],
                default="private",
                help_text="Component visibility level",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="component",
            name="gating_mode",
            field=models.CharField(
                blank=True,
                choices=[("approval_only", "Approval Only"), ("approval_plus_nda", "Approval + NDA")],
                help_text="Gating mode for gated components (only applies when visibility=gated)",
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="component",
            name="nda_document",
            field=models.ForeignKey(
                blank=True,
                help_text="Component-specific NDA document (if null and gating_mode=approval_plus_nda, uses company-wide NDA)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="component_ndas",
                to="documents.document",
            ),
        ),
        migrations.AlterIndexTogether(
            name="component",
            index_together=set(),
        ),
        migrations.AddIndex(
            model_name="component",
            index=models.Index(fields=["visibility"], name="sboms_component_visibility_idx"),
        ),
        migrations.AddIndex(
            model_name="component",
            index=models.Index(fields=["team", "visibility"], name="sboms_component_team_visibility_idx"),
        ),
    ]
