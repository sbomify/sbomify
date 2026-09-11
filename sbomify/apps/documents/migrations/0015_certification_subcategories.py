# Generated manually for the trust-center certification badges.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0014_rename_documents_a_team_id_838fe2_idx_documents_a_workspa_17946d_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="compliance_subcategory",
            field=models.CharField(
                blank=True,
                choices=[
                    ("nda", "NDA"),
                    ("soc2", "SOC 2"),
                    ("soc2-type1", "SOC 2 Type I"),
                    ("soc2-type2", "SOC 2 Type II"),
                    ("iso27001", "ISO 27001"),
                    ("cra", "CRA"),
                ],
                help_text="Compliance subcategory for auto-detection and badging",
                max_length=50,
                null=True,
            ),
        ),
    ]
