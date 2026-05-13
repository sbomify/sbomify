# Simplify component types: merge SBOM into BOM (ADR-006).
#
# All BOM-bearing components now use component_type='bom'. The SBOM type
# is removed — the bom_type field on the SBOM model already distinguishes
# between SBOM, VEX, CBOM, and other artifact types.

from django.db import migrations, models


def migrate_sbom_to_bom(apps, schema_editor):
    """Convert all component_type='sbom' rows to 'bom'."""
    Component = apps.get_model("sboms", "Component")
    Component.objects.filter(component_type="sbom").update(component_type="bom")


def reverse_bom_to_sbom(apps, schema_editor):
    """Reverse: convert 'bom' back to 'sbom' (best-effort — cannot distinguish original types)."""
    Component = apps.get_model("sboms", "Component")
    Component.objects.filter(component_type="bom").update(component_type="sbom")


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0054_add_bom_type_created_at_index"),
    ]

    operations = [
        # Step 1: Convert existing data
        migrations.RunPython(migrate_sbom_to_bom, reverse_bom_to_sbom),
        # Step 2: Update the field choices and default
        migrations.AlterField(
            model_name="component",
            name="component_type",
            field=models.CharField(
                choices=[("bom", "BOM"), ("document", "Document")],
                default="bom",
                help_text="Type of component (BOM, Document)",
                max_length=20,
            ),
        ),
    ]
