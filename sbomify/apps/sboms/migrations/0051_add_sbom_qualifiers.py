from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sboms", "0050_component_uuid_product_uuid_sbom_uuid"),
    ]

    operations = [
        migrations.AddField(
            model_name="sbom",
            name="qualifiers",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="PURL qualifiers distinguishing build variants (e.g., arch, distro). Canonicalized on save.",
            ),
        ),
        migrations.AddConstraint(
            model_name="sbom",
            constraint=models.UniqueConstraint(
                fields=["component", "version", "format", "qualifiers"],
                name="sboms_sbom_unique_component_version_format_qualifiers",
            ),
        ),
    ]
