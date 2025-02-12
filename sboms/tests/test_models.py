import pytest
from django.db import IntegrityError, transaction

from sboms.models import Component, Product, Project
from teams.fixtures import sample_team_with_owner_member  # noqa: F401


@pytest.mark.django_db
class TestUniqueConstraints:
    def test_duplicate_project_name_in_same_team(self, sample_team_with_owner_member):  # noqa: F811
        """Test that duplicate project names in the same team raise IntegrityError."""
        team = sample_team_with_owner_member.team

        # First project succeeds
        project = Project.objects.create(
            name="Project 1",
            team=team
        )

        # Second project with same name fails
        with pytest.raises(IntegrityError) as exc, transaction.atomic():
            Project.objects.create(
                name="Project 1",
                team=team
            )
        assert "duplicate key value violates unique constraint" in str(exc.value)
        assert "sboms_projects" in str(exc.value)

        # Clean up
        project.delete()

    def test_duplicate_product_name_in_same_team(self, sample_team_with_owner_member):  # noqa: F811
        """Test that duplicate product names in the same team raise IntegrityError."""
        team = sample_team_with_owner_member.team

        # First product succeeds
        product = Product.objects.create(
            name="Product 1",
            team=team
        )

        # Second product with same name fails
        with pytest.raises(IntegrityError) as exc, transaction.atomic():
            Product.objects.create(
                name="Product 1",
                team=team
            )
        assert "duplicate key value violates unique constraint" in str(exc.value)
        assert "sboms_products" in str(exc.value)

        # Clean up
        product.delete()

    def test_duplicate_component_name_in_same_team(self, sample_team_with_owner_member):  # noqa: F811
        """Test that duplicate component names in the same team raise IntegrityError."""
        team = sample_team_with_owner_member.team

        # First component succeeds
        component = Component.objects.create(
            name="Component 1",
            team=team
        )

        # Second component with same name fails
        with pytest.raises(IntegrityError) as exc, transaction.atomic():
            Component.objects.create(
                name="Component 1",
                team=team
            )
        assert "duplicate key value violates unique constraint" in str(exc.value)
        assert "sboms_components" in str(exc.value)

        # Clean up
        component.delete()