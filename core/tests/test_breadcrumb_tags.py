"""Test breadcrumb template tags."""

import pytest
from django.template import Context, Template
from django.test import RequestFactory

from core.models import Component, Product, Project
from teams.fixtures import sample_team_with_owner_member


@pytest.mark.django_db
class TestBreadcrumbTags:
    """Test breadcrumb template tags."""

    def test_breadcrumb_for_component_with_no_parents(self, sample_team_with_owner_member):
        """Test breadcrumb for component with no parent projects."""
        team = sample_team_with_owner_member.team

        # Create a component with no parent projects
        component = Component.objects.create(
            name="Test Component",
            team=team,
            is_public=True
        )

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' detailed=True %}
        """)

        context = Context({'component': component})
        result = template.render(context)

        # Should not contain any breadcrumb items since there are no parent relationships
        # and the current item is intentionally excluded
        assert '<li class="breadcrumb-item"' not in result
        # Should still contain the breadcrumb styling
        assert 'public-breadcrumb' in result

    def test_breadcrumb_for_component_with_public_project(self, sample_team_with_owner_member):
        """Test breadcrumb for component with public parent project."""
        team = sample_team_with_owner_member.team

        # Create a public project
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=True
        )

        # Create a public component
        component = Component.objects.create(
            name="Test Component",
            team=team,
            is_public=True
        )

        # Link component to project
        component.projects.add(project)

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' detailed=True %}
        """)

        context = Context({'component': component})
        result = template.render(context)

        # Should contain the project name in breadcrumbs
        assert "Test Project" in result
        # Should NOT contain the current component name (by design)
        assert "Test Component" not in result

    def test_breadcrumb_for_component_with_private_project(self, sample_team_with_owner_member):
        """Test breadcrumb for component with private parent project."""
        team = sample_team_with_owner_member.team

        # Create a private project
        project = Project.objects.create(
            name="Private Project",
            team=team,
            is_public=False
        )

        # Create a public component
        component = Component.objects.create(
            name="Test Component",
            team=team,
            is_public=True
        )

        # Link component to project
        component.projects.add(project)

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' detailed=True %}
        """)

        context = Context({'component': component})
        result = template.render(context)

        # Should not contain private project name
        assert "Private Project" not in result
        # Should not contain component name (by design) and no breadcrumb items
        assert "Test Component" not in result
        assert '<li class="breadcrumb-item"' not in result

    def test_breadcrumb_for_component_with_multiple_projects(self, sample_team_with_owner_member):
        """Test breadcrumb for component with multiple public parent projects."""
        team = sample_team_with_owner_member.team

        # Create multiple public projects
        project1 = Project.objects.create(
            name="Project One",
            team=team,
            is_public=True
        )
        project2 = Project.objects.create(
            name="Project Two",
            team=team,
            is_public=True
        )
        project3 = Project.objects.create(
            name="Project Three",
            team=team,
            is_public=True
        )

        # Create a public component
        component = Component.objects.create(
            name="Multi-Project Component",
            team=team,
            is_public=True
        )

        # Link component to all projects
        component.projects.add(project1, project2, project3)

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' %}
        """)

        context = Context({'component': component})
        result = template.render(context)

        # Should contain one project name (first one found)
        project_names = ["Project One", "Project Two", "Project Three"]
        found_projects = [name for name in project_names if name in result]
        assert len(found_projects) >= 1

        # Component name should NOT be in breadcrumbs (by design)
        assert "Multi-Project Component" not in result

    def test_breadcrumb_with_referrer_detection(self, sample_team_with_owner_member):
        """Test breadcrumb can detect parent from HTTP referrer."""
        team = sample_team_with_owner_member.team

        # Create multiple public projects
        project1 = Project.objects.create(
            name="Project One",
            team=team,
            is_public=True
        )
        project2 = Project.objects.create(
            name="Project Two",
            team=team,
            is_public=True
        )

        # Create a public component
        component = Component.objects.create(
            name="Test Component",
            team=team,
            is_public=True
        )

        # Link component to both projects
        component.projects.add(project1, project2)

        # Mock request with referrer pointing to project2
        factory = RequestFactory()
        request = factory.get(f'/public/component/{component.id}/')
        request.META['HTTP_REFERER'] = f'/public/project/{project2.id}/'

        # Test the breadcrumb template tag with referrer context
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' %}
        """)

        context = Context({'component': component, 'request': request})
        result = template.render(context)

        # Should contain Project Two (from referrer) but not Project One
        assert "Project Two" in result
        assert "Project One" not in result
        # Component name should NOT be in breadcrumbs (by design)
        assert "Test Component" not in result

    def test_breadcrumb_for_project_with_public_product(self, sample_team_with_owner_member):
        """Test breadcrumb for project with public parent product."""
        team = sample_team_with_owner_member.team

        # Create a public product
        product = Product.objects.create(
            name="Test Product",
            team=team,
            is_public=True
        )

        # Create a public project
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=True
        )

        # Link project to product
        project.products.add(product)

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb project 'project' %}
        """)

        context = Context({'project': project})
        result = template.render(context)

        # Should contain the product name in breadcrumbs
        assert "Test Product" in result
        # Should NOT contain the current project name (by design)
        assert "Test Project" not in result

    def test_breadcrumb_for_project_with_no_products(self, sample_team_with_owner_member):
        """Test breadcrumb for project with no parent products."""
        team = sample_team_with_owner_member.team

        # Create a project with no parent products
        project = Project.objects.create(
            name="Standalone Project",
            team=team,
            is_public=True
        )

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb project 'project' %}
        """)

        context = Context({'project': project})
        result = template.render(context)

        # Should not contain any breadcrumb items since there are no parent relationships
        assert '<li class="breadcrumb-item"' not in result
        # Should still contain the breadcrumb styling
        assert 'public-breadcrumb' in result

    def test_breadcrumb_for_product(self, sample_team_with_owner_member):
        """Test breadcrumb for product (should have no parents)."""
        team = sample_team_with_owner_member.team

        # Create a product
        product = Product.objects.create(
            name="Test Product",
            team=team,
            is_public=True
        )

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb product 'product' %}
        """)

        context = Context({'product': product})
        result = template.render(context)

        # Should not contain any breadcrumb items since products are top-level
        assert '<li class="breadcrumb-item"' not in result
        # Should still contain the breadcrumb styling
        assert 'public-breadcrumb' in result