# Enforce that each SBOM maps to exactly one ComponentRelease.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_component_release_indexes"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="componentreleaseartifact",
            constraint=models.UniqueConstraint(
                fields=["sbom"],
                name="unique_sbom_one_component_release",
            ),
        ),
    ]
