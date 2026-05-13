"""Add bom_type discriminator field to SBOM model (ADR-006).

Adds BomType enum and bom_type field (default "sbom"), updates the unique
constraint to include bom_type, and adds BOM to ComponentType choices.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0052_remove_componentidentifier"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="sbom",
            name="sboms_sbom_unique_component_version_format_qualifiers",
        ),
        migrations.AddField(
            model_name="sbom",
            name="bom_type",
            field=models.CharField(
                choices=[
                    ("sbom", "SBOM"),
                    ("cbom", "CBOM"),
                    ("aibom", "AI BOM"),
                    ("hbom", "HBOM"),
                    ("vex", "VEX"),
                    ("saasbom", "SaaSBOM"),
                    ("obom", "OBOM"),
                    ("mbom", "MBOM"),
                ],
                default="sbom",
                help_text="Type of BOM artifact. See ADR-006.",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="component",
            name="component_type",
            field=models.CharField(
                choices=[("sbom", "SBOM"), ("document", "Document"), ("bom", "BOM")],
                default="sbom",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="sbom",
            constraint=models.UniqueConstraint(
                fields=("component", "version", "format", "qualifiers", "bom_type"),
                name="sboms_sbom_unique_component_version_format_qualifiers_bom_type",
            ),
        ),
    ]
