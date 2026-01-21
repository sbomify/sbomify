# Generated manually for gated documents feature

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0005_document_documents_d_created_bd50af_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="content_hash",
            field=models.CharField(
                blank=True,
                help_text="SHA-256 hash of document content for verification",
                max_length=64,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="compliance_subcategory",
            field=models.CharField(
                blank=True,
                choices=[("nda", "NDA"), ("soc2", "SOC 2"), ("iso27001", "ISO 27001")],
                help_text="Compliance subcategory for auto-detection and badging",
                max_length=50,
                null=True,
            ),
        ),
    ]
