"""Test breadcrumb template tags."""

import pytest
from django.template import Context, Template
from django.test import RequestFactory

from sbomify.apps.core.models import Component, Product, Project
from sbomify.apps.teams.fixtures import sample_team_with_owner_member


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
            {% breadcrumb component 'component' %}
        """)

        context = Context({'component': component})
        result = template.render(context)

        # Should not contain any breadcrumb items since there are no parent relationships
        # and the current item is intentionally excluded
        assert '<li class="breadcrumb-item"' not in result
        # Should still contain the breadcrumb styling
        assert 'public-breadcrumb' in result

    def test_breadcrumb_for_component_with_public_project(self, sample_team_with_owner_member):
        """Test breadcrumb for component with public parent project and product."""
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
        project.products.add(product)

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
            {% breadcrumb component 'component' %}
        """)

        context = Context({'component': component})
        result = template.render(context)

        # Should contain the product name in breadcrumbs (not project)
        assert "Test Product" in result
        # Should NOT contain the project name (projects no longer in breadcrumb path)
        assert "Test Project" not in result
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
            {% breadcrumb component 'component' %}
        """)

        context = Context({'component': component})
        result = template.render(context)

        # Should not contain private project name
        assert "Private Project" not in result
        # Should not contain component name (by design) and no breadcrumb items
        assert "Test Component" not in result
        assert '<li class="breadcrumb-item"' not in result

    def test_breadcrumb_for_component_with_multiple_projects(self, sample_team_with_owner_member):
        """Test breadcrumb for component with multiple public parent projects showing product."""
        team = sample_team_with_owner_member.team

        # Create a public product
        product = Product.objects.create(
            name="Parent Product",
            team=team,
            is_public=True
        )

        # Create multiple public projects
        project1 = Project.objects.create(
            name="Project One",
            team=team,
            is_public=True
        )
        project1.products.add(product)
        project2 = Project.objects.create(
            name="Project Two",
            team=team,
            is_public=True
        )
        project2.products.add(product)
        project3 = Project.objects.create(
            name="Project Three",
            team=team,
            is_public=True
        )
        project3.products.add(product)

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

        # Should contain the product name (projects are no longer shown)
        assert "Parent Product" in result

        # Component name should NOT be in breadcrumbs (by design)
        assert "Multi-Project Component" not in result

    def test_breadcrumb_with_referrer_detection(self, sample_team_with_owner_member):
        """Test breadcrumb can detect parent product from HTTP referrer."""
        team = sample_team_with_owner_member.team

        # Create multiple public products
        product1 = Product.objects.create(
            name="Product One",
            team=team,
            is_public=True
        )
        product2 = Product.objects.create(
            name="Product Two",
            team=team,
            is_public=True
        )

        # Create projects for each product
        project1 = Project.objects.create(
            name="Project One",
            team=team,
            is_public=True
        )
        project1.products.add(product1)

        project2 = Project.objects.create(
            name="Project Two",
            team=team,
            is_public=True
        )
        project2.products.add(product2)

        # Create a public component
        component = Component.objects.create(
            name="Test Component",
            team=team,
            is_public=True
        )

        # Link component to both projects
        component.projects.add(project1, project2)

        # Mock request with referrer pointing to product2's page
        factory = RequestFactory()
        request = factory.get(f'/public/component/{component.id}/')
        # Set referrer to product2's public URL - the breadcrumb should detect this
        request.META['HTTP_REFERER'] = f'/public/product/{product2.id}/'

        # Test the breadcrumb template tag with referrer context
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' %}
        """)

        context = Context({'component': component, 'request': request})
        result = template.render(context)

        # Should contain Product Two (from referrer) but not Product One
        assert "Product Two" in result
        assert "Product One" not in result
        # Component name should NOT be in breadcrumbs (by design)
        assert "Test Component" not in result

    def test_breadcrumb_for_project_redirects(self, sample_team_with_owner_member):
        """Test breadcrumb for project item type - not used anymore since projects redirect."""
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

        # Test the breadcrumb template tag - should return empty since 'project' type is not handled
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb project 'project' %}
        """)

        context = Context({'project': project})
        result = template.render(context)

        # Projects no longer have standalone pages, so breadcrumbs return empty
        assert '<li class="breadcrumb-item"' not in result

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
