# Generated manually for component release performance indexes

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0023_populate_component_releases"),
    ]

    operations = [
        # Compound index for TEA API queries: filter by component, order by -created_at
        migrations.AddIndex(
            model_name="componentrelease",
            index=models.Index(
                fields=["component", "-created_at"],
                name="core_cr_component_created_idx",
            ),
        ),
        # Update related_name on ComponentReleaseArtifact.sbom FK
        migrations.AlterField(
            model_name="componentreleaseartifact",
            name="sbom",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="component_release_artifacts",
                to="sboms.sbom",
            ),
        ),
    ]
