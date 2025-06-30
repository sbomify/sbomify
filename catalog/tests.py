# Create your tests here.

"""Tests for catalog app models.

These tests are duplicated from sboms.tests to ensure the catalog models
work correctly during the migration process.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from catalog.models import Component, Product, ProductProject, Project, ProjectComponent
from teams.fixtures import sample_team_with_owner_member  # noqa: F401
from teams.models import Team


@pytest.mark.django_db
class TestCatalogUniqueConstraints:
    """Test unique constraints for catalog models.

    These tests are duplicated from sboms.tests.test_models.TestUniqueConstraints
    to ensure catalog models maintain the same constraints.
    """

    def test_duplicate_project_name_in_same_team(self, sample_team_with_owner_member):  # noqa: F811
        """Test that duplicate project names in the same team raise IntegrityError."""
        team = sample_team_with_owner_member.team

        # First project succeeds
        project = Project.objects.create(name="Project 1", team=team)

        # Second project with same name fails
        with pytest.raises(IntegrityError) as exc, transaction.atomic():
            Project.objects.create(name="Project 1", team=team)
        assert any(
            msg in str(exc.value)
            for msg in ["duplicate key value violates unique constraint", "UNIQUE constraint failed"]
        )

        # Clean up
        project.delete()

    def test_duplicate_product_name_in_same_team(self, sample_team_with_owner_member):  # noqa: F811
        """Test that duplicate product names in the same team raise IntegrityError."""
        team = sample_team_with_owner_member.team

        # First product succeeds
        product = Product.objects.create(name="Product 1", team=team)

        # Second product with same name fails
        with pytest.raises(IntegrityError) as exc, transaction.atomic():
            Product.objects.create(name="Product 1", team=team)
        assert any(
            msg in str(exc.value)
            for msg in ["duplicate key value violates unique constraint", "UNIQUE constraint failed"]
        )

        # Clean up
        product.delete()

    def test_duplicate_component_name_in_same_team(self, sample_team_with_owner_member):  # noqa: F811
        """Test that duplicate component names in the same team raise IntegrityError."""
        team = sample_team_with_owner_member.team

        # First component succeeds
        component = Component.objects.create(name="Component 1", team=team)

        # Second component with same name fails
        with pytest.raises(IntegrityError) as exc, transaction.atomic():
            Component.objects.create(name="Component 1", team=team)
        assert any(
            msg in str(exc.value)
            for msg in ["duplicate key value violates unique constraint", "UNIQUE constraint failed"]
        )

        # Clean up
        component.delete()

    def test_duplicate_names_allowed_across_teams(self, django_user_model):
        """Test that duplicate names are allowed across different teams."""
        # Create two different teams
        team1 = Team.objects.create(name="Team 1")
        team2 = Team.objects.create(name="Team 2")

        # Same names should be allowed across different teams
        product1 = Product.objects.create(name="Shared Name", team=team1)
        product2 = Product.objects.create(name="Shared Name", team=team2)

        project1 = Project.objects.create(name="Shared Name", team=team1)
        project2 = Project.objects.create(name="Shared Name", team=team2)

        component1 = Component.objects.create(name="Shared Name", team=team1)
        component2 = Component.objects.create(name="Shared Name", team=team2)

        # All should succeed
        assert product1.name == product2.name
        assert project1.name == project2.name
        assert component1.name == component2.name


@pytest.mark.django_db
class TestCatalogModelCreation:
    """Test basic model creation for catalog models."""

    def test_product_creation(self, sample_team_with_owner_member):  # noqa: F811
        """Test creating a product with minimal required fields."""
        team = sample_team_with_owner_member.team

        product = Product.objects.create(name="Test Product", team=team)

        assert product.name == "Test Product"
        assert product.team == team
        assert product.is_public is False  # Default value
        assert product.created_at is not None
        assert str(product) == f"Test Product(Team ID: {team.id})"
        assert len(product.id) == 12  # Generated ID length

    def test_project_creation(self, sample_team_with_owner_member):  # noqa: F811
        """Test creating a project with minimal required fields."""
        team = sample_team_with_owner_member.team

        project = Project.objects.create(name="Test Project", team=team)

        assert project.name == "Test Project"
        assert project.team == team
        assert project.is_public is False  # Default value
        assert project.metadata == {}  # Default value
        assert project.created_at is not None
        assert str(project) == f"<{project.id}> Test Project"
        assert len(project.id) == 12  # Generated ID length

    def test_component_creation(self, sample_team_with_owner_member):  # noqa: F811
        """Test creating a component with minimal required fields."""
        team = sample_team_with_owner_member.team

        component = Component.objects.create(name="Test Component", team=team)

        assert component.name == "Test Component"
        assert component.team == team
        assert component.is_public is False  # Default value
        assert component.metadata == {}  # Default value
        assert component.created_at is not None
        assert str(component) == "Test Component"
        assert len(component.id) == 12  # Generated ID length


@pytest.mark.django_db
class TestCatalogFieldValidation:
    """Test field validation for catalog models."""

    def test_blank_name_validation(self, sample_team_with_owner_member):  # noqa: F811
        """Test that blank names are not allowed."""
        team = sample_team_with_owner_member.team

        # Test blank names are rejected
        with pytest.raises(ValidationError):
            product = Product(name="", team=team)
            product.full_clean()

        with pytest.raises(ValidationError):
            project = Project(name="", team=team)
            project.full_clean()

        with pytest.raises(ValidationError):
            component = Component(name="", team=team)
            component.full_clean()

    def test_long_names(self, sample_team_with_owner_member):  # noqa: F811
        """Test handling of long names (up to 255 characters)."""
        team = sample_team_with_owner_member.team
        long_name = "A" * 255

        # Should work at max length
        product = Product.objects.create(name=long_name, team=team)
        assert product.name == long_name

        project = Project.objects.create(name=long_name, team=team)
        assert project.name == long_name

        component = Component.objects.create(name=long_name, team=team)
        assert component.name == long_name

    def test_special_characters_in_names(self, sample_team_with_owner_member):  # noqa: F811
        """Test that special characters are allowed in names."""
        team = sample_team_with_owner_member.team
        special_name = "Test-Component_v1.0.0 (beta) [final]"

        product = Product.objects.create(name=special_name, team=team)
        assert product.name == special_name

        project = Project.objects.create(name=special_name, team=team)
        assert project.name == special_name

        component = Component.objects.create(name=special_name, team=team)
        assert component.name == special_name


@pytest.mark.django_db
class TestCatalogMetadataField:
    """Test JSON metadata field behavior."""

    def test_default_metadata(self, sample_team_with_owner_member):  # noqa: F811
        """Test that metadata defaults to empty dict."""
        team = sample_team_with_owner_member.team

        project = Project.objects.create(name="Test Project", team=team)
        component = Component.objects.create(name="Test Component", team=team)

        assert project.metadata == {}
        assert component.metadata == {}

    def test_complex_metadata(self, sample_team_with_owner_member):  # noqa: F811
        """Test storing complex metadata structures."""
        team = sample_team_with_owner_member.team

        complex_metadata = {
            "version": "1.0.0",
            "description": "Test project with complex metadata",
            "tags": ["backend", "api", "python"],
            "config": {
                "database": "postgresql",
                "cache": "redis",
                "features": {"auth": True, "billing": False},
            },
            "numbers": [1, 2, 3.14, -42],
        }

        project = Project.objects.create(name="Test Project", team=team, metadata=complex_metadata)

        # Reload from database
        project.refresh_from_db()
        assert project.metadata == complex_metadata
        assert project.metadata["version"] == "1.0.0"
        assert project.metadata["config"]["features"]["auth"] is True

    def test_metadata_updates(self, sample_team_with_owner_member):  # noqa: F811
        """Test updating metadata fields."""
        team = sample_team_with_owner_member.team

        project = Project.objects.create(name="Test Project", team=team, metadata={"version": "1.0.0"})

        # Update metadata
        project.metadata["version"] = "1.1.0"
        project.metadata["description"] = "Updated description"
        project.save()

        project.refresh_from_db()
        assert project.metadata["version"] == "1.1.0"
        assert project.metadata["description"] == "Updated description"


@pytest.mark.django_db
class TestCatalogModelRelationships:
    """Test relationships between catalog models."""

    def test_product_project_relationship(self, sample_team_with_owner_member):  # noqa: F811
        """Test many-to-many relationship between products and projects."""
        team = sample_team_with_owner_member.team

        product = Product.objects.create(name="Test Product", team=team)
        project1 = Project.objects.create(name="Test Project 1", team=team)
        project2 = Project.objects.create(name="Test Project 2", team=team)

        # Add projects to product
        product.projects.add(project1, project2)

        assert product.projects.count() == 2
        assert project1 in product.projects.all()
        assert project2 in product.projects.all()

        # Check reverse relationship
        assert product in project1.products.all()
        assert product in project2.products.all()

    def test_project_component_relationship(self, sample_team_with_owner_member):  # noqa: F811
        """Test many-to-many relationship between projects and components."""
        team = sample_team_with_owner_member.team

        project = Project.objects.create(name="Test Project", team=team)
        component1 = Component.objects.create(name="Test Component 1", team=team)
        component2 = Component.objects.create(name="Test Component 2", team=team)

        # Add components to project
        project.components.add(component1, component2)

        assert project.components.count() == 2
        assert component1 in project.components.all()
        assert component2 in project.components.all()

        # Check reverse relationship
        assert project in component1.projects.all()
        assert project in component2.projects.all()

    def test_related_name_functionality(self, sample_team_with_owner_member):  # noqa: F811
        """Test that related_name attributes work correctly."""
        team = sample_team_with_owner_member.team

        product = Product.objects.create(name="Test Product", team=team)
        project = Project.objects.create(name="Test Project", team=team)
        component = Component.objects.create(name="Test Component", team=team)

        # Test accessing via related_name
        assert product in team.catalog_products.all()
        assert project in team.catalog_projects.all()
        assert component in team.catalog_components.all()

        # Test that these don't conflict with sboms models
        assert hasattr(team, "catalog_products")
        assert hasattr(team, "catalog_projects")
        assert hasattr(team, "catalog_components")


@pytest.mark.django_db
class TestCatalogThroughModels:
    """Test the through models (ProductProject, ProjectComponent)."""

    def test_product_project_through_model(self, sample_team_with_owner_member):  # noqa: F811
        """Test ProductProject through model functionality."""
        team = sample_team_with_owner_member.team

        product = Product.objects.create(name="Test Product", team=team)
        project = Project.objects.create(name="Test Project", team=team)

        # Create through model instance
        pp = ProductProject.objects.create(product=product, project=project)

        assert pp.product == product
        assert pp.project == project
        assert len(pp.id) == 12  # Generated ID
        assert str(pp) == f"{product.id} - {project.id}"

        # Verify relationship through through model
        assert ProductProject.objects.filter(product=product, project=project).exists()

    def test_project_component_through_model(self, sample_team_with_owner_member):  # noqa: F811
        """Test ProjectComponent through model functionality."""
        team = sample_team_with_owner_member.team

        project = Project.objects.create(name="Test Project", team=team)
        component = Component.objects.create(name="Test Component", team=team)

        # Create through model instance
        pc = ProjectComponent.objects.create(project=project, component=component)

        assert pc.project == project
        assert pc.component == component
        assert len(pc.id) == 12  # Generated ID
        assert str(pc) == f"{project.id} - {component.id}"

        # Verify relationship through through model
        assert ProjectComponent.objects.filter(project=project, component=component).exists()

    def test_through_model_unique_constraints(self, sample_team_with_owner_member):  # noqa: F811
        """Test unique constraints on through models."""
        team = sample_team_with_owner_member.team

        # Create new instances for this test to avoid conflicts
        product = Product.objects.create(name="Unique Test Product", team=team)
        project = Project.objects.create(name="Unique Test Project", team=team)
        component = Component.objects.create(name="Unique Test Component", team=team)

        # First relationship succeeds
        ProductProject.objects.create(product=product, project=project)
        ProjectComponent.objects.create(project=project, component=component)

        # Duplicate relationships should fail
        with pytest.raises(IntegrityError), transaction.atomic():
            ProductProject.objects.create(product=product, project=project)

        with pytest.raises(IntegrityError), transaction.atomic():
            ProjectComponent.objects.create(project=project, component=component)

    def test_through_model_cascade_deletion(self, sample_team_with_owner_member):  # noqa: F811
        """Test that through models are deleted when parent models are deleted."""
        team = sample_team_with_owner_member.team

        product = Product.objects.create(name="Test Product For Deletion", team=team)
        project = Project.objects.create(name="Test Project For Deletion", team=team)
        component = Component.objects.create(name="Test Component For Deletion", team=team)

        pp = ProductProject.objects.create(product=product, project=project)
        pc = ProjectComponent.objects.create(project=project, component=component)

        # Delete parent models
        product.delete()
        component.delete()

        # Through models should also be deleted
        assert not ProductProject.objects.filter(id=pp.id).exists()
        assert not ProjectComponent.objects.filter(id=pc.id).exists()


@pytest.mark.django_db
class TestCatalogModelOrdering:
    """Test model ordering for catalog models."""

    def test_product_ordering(self, sample_team_with_owner_member):  # noqa: F811
        """Test that products are ordered by name."""
        team = sample_team_with_owner_member.team

        product_z = Product.objects.create(name="Z Product", team=team)
        product_a = Product.objects.create(name="A Product", team=team)
        product_m = Product.objects.create(name="M Product", team=team)

        products = list(Product.objects.all())
        assert products[0] == product_a
        assert products[1] == product_m
        assert products[2] == product_z

    def test_project_ordering(self, sample_team_with_owner_member):  # noqa: F811
        """Test that projects are ordered by name."""
        team = sample_team_with_owner_member.team

        project_z = Project.objects.create(name="Z Project", team=team)
        project_a = Project.objects.create(name="A Project", team=team)
        project_m = Project.objects.create(name="M Project", team=team)

        projects = list(Project.objects.all())
        assert projects[0] == project_a
        assert projects[1] == project_m
        assert projects[2] == project_z

    def test_component_ordering(self, sample_team_with_owner_member):  # noqa: F811
        """Test that components are ordered by name."""
        team = sample_team_with_owner_member.team

        component_z = Component.objects.create(name="Z Component", team=team)
        component_a = Component.objects.create(name="A Component", team=team)
        component_m = Component.objects.create(name="M Component", team=team)

        components = list(Component.objects.all())
        assert components[0] == component_a
        assert components[1] == component_m
        assert components[2] == component_z


@pytest.mark.django_db
class TestCatalogModelEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_unicode_names(self, sample_team_with_owner_member):  # noqa: F811
        """Test that unicode characters work in names."""
        team = sample_team_with_owner_member.team

        unicode_name = "测试产品 🚀 المنتج الاختباري"

        product = Product.objects.create(name=unicode_name, team=team)
        project = Project.objects.create(name=unicode_name, team=team)
        component = Component.objects.create(name=unicode_name, team=team)

        assert product.name == unicode_name
        assert project.name == unicode_name
        assert component.name == unicode_name

    def test_boolean_field_values(self, sample_team_with_owner_member):  # noqa: F811
        """Test boolean field behavior."""
        team = sample_team_with_owner_member.team

        # Test explicit True
        product = Product.objects.create(name="Public Product", team=team, is_public=True)
        assert product.is_public is True

        # Test explicit False
        project = Project.objects.create(name="Private Project", team=team, is_public=False)
        assert project.is_public is False

        # Test default (should be False)
        component = Component.objects.create(name="Default Component", team=team)
        assert component.is_public is False

    def test_complex_relationship_scenarios(self, sample_team_with_owner_member):  # noqa: F811
        """Test complex relationship scenarios."""
        team = sample_team_with_owner_member.team

        # Create multiple products, projects, and components
        products = [Product.objects.create(name=f"Product {i}", team=team) for i in range(3)]
        projects = [Project.objects.create(name=f"Project {i}", team=team) for i in range(4)]
        components = [Component.objects.create(name=f"Component {i}", team=team) for i in range(5)]

        # Create complex many-to-many relationships
        # Product 0 has projects 0, 1
        products[0].projects.add(projects[0], projects[1])
        # Product 1 has projects 1, 2, 3
        products[1].projects.add(projects[1], projects[2], projects[3])
        # Product 2 has project 0
        products[2].projects.add(projects[0])

        # Project 0 has components 0, 1, 2
        projects[0].components.add(components[0], components[1], components[2])
        # Project 1 has components 1, 3
        projects[1].components.add(components[1], components[3])
        # Project 2 has components 2, 4
        projects[2].components.add(components[2], components[4])

        # Verify complex relationships
        assert products[0].projects.count() == 2
        assert products[1].projects.count() == 3
        assert projects[1].products.count() == 2  # Belongs to products 0 and 1
        assert projects[0].components.count() == 3
        assert components[1].projects.count() == 2  # Belongs to projects 0 and 1

    def test_model_meta_options(self, sample_team_with_owner_member):  # noqa: F811
        """Test that model meta options are correctly set."""
        # Test db_table settings
        assert Product._meta.db_table == "sboms_products"
        assert Project._meta.db_table == "sboms_projects"
        assert Component._meta.db_table == "sboms_components"
        assert ProductProject._meta.db_table == "sboms_products_projects"
        assert ProjectComponent._meta.db_table == "sboms_projects_components"

        # Test managed=False
        assert Product._meta.managed is False
        assert Project._meta.managed is False
        assert Component._meta.managed is False
        assert ProductProject._meta.managed is False
        assert ProjectComponent._meta.managed is False


@pytest.mark.django_db
class TestCatalogDataIntegrity:
    """Test data integrity and consistency."""

    def test_bulk_operations(self, sample_team_with_owner_member):  # noqa: F811
        """Test bulk create/update operations."""
        team = sample_team_with_owner_member.team

        # Bulk create products
        products = Product.objects.bulk_create(
            [Product(name=f"Bulk Product {i}", team=team) for i in range(10)]
        )
        assert len(products) == 10
        assert Product.objects.filter(team=team, name__startswith="Bulk Product").count() == 10

        # Bulk create projects
        projects = Project.objects.bulk_create(
            [Project(name=f"Bulk Project {i}", team=team) for i in range(5)]
        )
        assert len(projects) == 5
        assert Project.objects.filter(team=team, name__startswith="Bulk Project").count() == 5

    def test_queryset_filtering(self, sample_team_with_owner_member):  # noqa: F811
        """Test basic queryset filtering works correctly."""
        team = sample_team_with_owner_member.team

        # Create test data
        public_product = Product.objects.create(name="Public Product", team=team, is_public=True)
        private_product = Product.objects.create(name="Private Product", team=team, is_public=False)

        # Test filtering
        public_products = Product.objects.filter(is_public=True)
        private_products = Product.objects.filter(is_public=False)

        assert public_product in public_products
        assert private_product in private_products
        assert public_product not in private_products
        assert private_product not in public_products
