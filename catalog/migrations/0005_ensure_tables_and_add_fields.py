# Migration to ensure tables exist and add component_type field
from django.db import migrations, models, connection
import django.db.models.deletion
import core.utils


def ensure_base_tables_exist(apps, schema_editor):
    """Ensure base tables exist before adding new fields."""
    with connection.cursor() as cursor:
        # Check if sboms_products table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'sboms_products'
            );
        """)
        tables_exist = cursor.fetchone()[0]

        if not tables_exist:
            # Create base tables with full structure matching current models
            # This handles fresh environments (like Docker) where sboms migrations haven't run

            # Products table
            cursor.execute("""
                CREATE TABLE sboms_products (
                    id VARCHAR(20) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    is_public BOOLEAN NOT NULL DEFAULT FALSE,
                    team_id INTEGER NOT NULL REFERENCES teams_team(id) ON DELETE CASCADE,
                    UNIQUE(team_id, name)
                );
            """)
            cursor.execute("CREATE INDEX sboms_products_team_id_idx ON sboms_products(team_id);")

            # Projects table
            cursor.execute("""
                CREATE TABLE sboms_projects (
                    id VARCHAR(20) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    is_public BOOLEAN NOT NULL DEFAULT FALSE,
                    metadata JSONB NOT NULL DEFAULT '{}',
                    team_id INTEGER NOT NULL REFERENCES teams_team(id) ON DELETE CASCADE,
                    UNIQUE(team_id, name)
                );
            """)
            cursor.execute("CREATE INDEX sboms_projects_team_id_idx ON sboms_projects(team_id);")

            # Components table (without component_type - we'll add it next)
            cursor.execute("""
                CREATE TABLE sboms_components (
                    id VARCHAR(20) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    is_public BOOLEAN NOT NULL DEFAULT FALSE,
                    metadata JSONB NOT NULL DEFAULT '{}',
                    team_id INTEGER NOT NULL REFERENCES teams_team(id) ON DELETE CASCADE,
                    UNIQUE(team_id, name)
                );
            """)
            cursor.execute("CREATE INDEX sboms_components_team_id_idx ON sboms_components(team_id);")

            # ProductProject through table
            cursor.execute("""
                CREATE TABLE sboms_products_projects (
                    id VARCHAR(20) PRIMARY KEY,
                    product_id VARCHAR(20) NOT NULL REFERENCES sboms_products(id) ON DELETE CASCADE,
                    project_id VARCHAR(20) NOT NULL REFERENCES sboms_projects(id) ON DELETE CASCADE,
                    UNIQUE(product_id, project_id)
                );
            """)
            cursor.execute("CREATE INDEX sboms_products_projects_product_id_idx ON sboms_products_projects(product_id);")
            cursor.execute("CREATE INDEX sboms_products_projects_project_id_idx ON sboms_products_projects(project_id);")

            # ProjectComponent through table
            cursor.execute("""
                CREATE TABLE sboms_projects_components (
                    id VARCHAR(20) PRIMARY KEY,
                    project_id VARCHAR(20) NOT NULL REFERENCES sboms_projects(id) ON DELETE CASCADE,
                    component_id VARCHAR(20) NOT NULL REFERENCES sboms_components(id) ON DELETE CASCADE,
                    UNIQUE(project_id, component_id)
                );
            """)
            cursor.execute("CREATE INDEX sboms_projects_components_project_id_idx ON sboms_projects_components(project_id);")
            cursor.execute("CREATE INDEX sboms_projects_components_component_id_idx ON sboms_projects_components(component_id);")


def reverse_base_tables(apps, schema_editor):
    """Reverse operation - we can't safely remove tables."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_alter_component_options_alter_product_options_and_more"),
        ("teams", "0014_update_team_keys"),
    ]

    operations = [
        # First ensure base tables exist (for fresh environments like Docker)
        migrations.RunPython(ensure_base_tables_exist, reverse_base_tables),

        # Then add all missing fields that are in models but not in migration history
        migrations.AddField(
            model_name="component",
            name="component_type",
            field=models.CharField(
                choices=[("sbom", "SBOM")], default="sbom", max_length=20
            ),
        ),
        migrations.AddField(
            model_name="component",
            name="team",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="catalog_components",
                to="teams.team",
                null=True  # Temporarily nullable for safe migration
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="team",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="catalog_products",
                to="teams.team",
                null=True  # Temporarily nullable for safe migration
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="team",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="catalog_projects",
                to="teams.team",
                null=True  # Temporarily nullable for safe migration
            ),
        ),
        migrations.AddField(
            model_name="component",
            name="projects",
            field=models.ManyToManyField(
                through="catalog.ProjectComponent", to="catalog.project"
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="projects",
            field=models.ManyToManyField(
                through="catalog.ProductProject", to="catalog.project"
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="products",
            field=models.ManyToManyField(
                through="catalog.ProductProject", to="catalog.product"
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="components",
            field=models.ManyToManyField(
                through="catalog.ProjectComponent", to="catalog.component"
            ),
        ),
        migrations.AddField(
            model_name="productproject",
            name="product",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="catalog.product",
                null=True  # Temporarily nullable for safe migration
            ),
        ),
        migrations.AddField(
            model_name="productproject",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="catalog.project",
                null=True  # Temporarily nullable for safe migration
            ),
        ),
        migrations.AddField(
            model_name="projectcomponent",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="catalog.project",
                null=True  # Temporarily nullable for safe migration
            ),
        ),
        migrations.AddField(
            model_name="projectcomponent",
            name="component",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="catalog.component",
                null=True  # Temporarily nullable for safe migration
            ),
        ),
    ]