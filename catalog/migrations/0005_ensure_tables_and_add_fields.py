# Migration to add missing component_type field and sync Django state
# Some fields exist in production (team_id), others don't (component_type)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0004_alter_component_options_alter_product_options_and_more"),
        ("teams", "0001_initial"),
    ]

    operations = [
        # Actually add component_type field (doesn't exist in production)
        migrations.AddField(
            model_name="component",
            name="component_type",
            field=models.CharField(choices=[("sbom", "SBOM")], default="sbom", max_length=20),
        ),
        # Use SeparateDatabaseAndState for fields that already exist in production
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # These tell Django about fields that already exist
                migrations.AddField(
                    model_name="component",
                    name="team",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="catalog_components",
                        to="teams.team",
                    ),
                ),
                migrations.AddField(
                    model_name="product",
                    name="team",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="catalog_products",
                        to="teams.team",
                    ),
                ),
                migrations.AddField(
                    model_name="project",
                    name="team",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="catalog_projects",
                        to="teams.team",
                    ),
                ),
                migrations.AddField(
                    model_name="component",
                    name="projects",
                    field=models.ManyToManyField(through="catalog.ProjectComponent", to="catalog.project"),
                ),
                migrations.AddField(
                    model_name="product",
                    name="projects",
                    field=models.ManyToManyField(through="catalog.ProductProject", to="catalog.project"),
                ),
                migrations.AddField(
                    model_name="project",
                    name="products",
                    field=models.ManyToManyField(through="catalog.ProductProject", to="catalog.product"),
                ),
                migrations.AddField(
                    model_name="project",
                    name="components",
                    field=models.ManyToManyField(through="catalog.ProjectComponent", to="catalog.component"),
                ),
                migrations.AddField(
                    model_name="productproject",
                    name="product",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="catalog.product",
                    ),
                ),
                migrations.AddField(
                    model_name="productproject",
                    name="project",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="catalog.project",
                    ),
                ),
                migrations.AddField(
                    model_name="projectcomponent",
                    name="project",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="catalog.project",
                    ),
                ),
                migrations.AddField(
                    model_name="projectcomponent",
                    name="component",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="catalog.component",
                    ),
                ),
            ],
            # Empty database operations - these fields already exist
            database_operations=[],
        ),
    ]
