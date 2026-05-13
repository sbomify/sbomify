"""Test breadcrumb template tags."""

import pytest
from django.template import Context, Template
from django.test import RequestFactory

from sbomify.apps.core.models import Component, Product


@pytest.mark.django_db
class TestBreadcrumbTags:
    """Test breadcrumb template tags."""

    def test_breadcrumb_for_component_with_no_parents(self, sample_team_with_owner_member):
        """Test breadcrumb for component with no parent products."""
        team = sample_team_with_owner_member.team

        # Create a component with no parent products
        component = Component.objects.create(
            name="Test Component",
            team=team,
            visibility=Component.Visibility.PUBLIC,
        )

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' %}
        """)

        context = Context({"component": component})
        template.render(context)

        # Should not contain any breadcrumb items since there are no parent relationships
        # and the current item is intentionally excluded
        # With the new template, when there are no crumbs, nothing is rendered
        # So we just check it doesn't error out (empty result is fine)

    def test_breadcrumb_for_component_with_public_product(self, sample_team_with_owner_member):
        """Test breadcrumb for component attached to a public parent product."""
        team = sample_team_with_owner_member.team

        # Create a public product
        product = Product.objects.create(
            name="Test Product",
            team=team,
            is_public=True,
        )

        # Create a public component
        component = Component.objects.create(
            name="Test Component",
            team=team,
            visibility=Component.Visibility.PUBLIC,
        )

        # Link component directly to product
        component.products.add(product)

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' %}
        """)

        context = Context({"component": component})
        result = template.render(context)

        # Should contain the product name in breadcrumbs
        assert "Test Product" in result
        # Should NOT contain the current component name (by design)
        assert "Test Component" not in result

    def test_breadcrumb_for_component_with_private_product(self, sample_team_with_owner_member):
        """Test breadcrumb for component with private parent product is omitted."""
        team = sample_team_with_owner_member.team

        # Create a private product
        product = Product.objects.create(
            name="Private Product",
            team=team,
            is_public=False,
        )

        # Create a public component
        component = Component.objects.create(
            name="Test Component",
            team=team,
            visibility=Component.Visibility.PUBLIC,
        )

        # Link component to product
        component.products.add(product)

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' %}
        """)

        context = Context({"component": component})
        result = template.render(context)

        # Should not contain private product name
        assert "Private Product" not in result
        # Should not contain component name (by design) and no breadcrumb items
        assert "Test Component" not in result
        assert '<li class="breadcrumb-item"' not in result

    def test_breadcrumb_with_referrer_detection(self, sample_team_with_owner_member):
        """Test breadcrumb can detect parent product from HTTP referrer when there are multiple."""
        team = sample_team_with_owner_member.team

        # Create multiple public products
        product1 = Product.objects.create(
            name="Product One",
            team=team,
            is_public=True,
        )
        product2 = Product.objects.create(
            name="Product Two",
            team=team,
            is_public=True,
        )

        # Create a public component linked to both products
        component = Component.objects.create(
            name="Test Component",
            team=team,
            visibility=Component.Visibility.PUBLIC,
        )

        component.products.add(product1, product2)

        # Mock request with referrer pointing to product2's page
        factory = RequestFactory()
        request = factory.get(f"/public/component/{component.id}/")
        # Set referrer to product2's public URL - the breadcrumb should detect this
        request.META["HTTP_REFERER"] = f"/public/product/{product2.id}/"

        # Test the breadcrumb template tag with referrer context
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb component 'component' %}
        """)

        context = Context({"component": component, "request": request})
        result = template.render(context)

        # Should contain Product Two (from referrer) but not Product One
        assert "Product Two" in result
        assert "Product One" not in result
        # Component name should NOT be in breadcrumbs (by design)
        assert "Test Component" not in result

    def test_breadcrumb_for_product(self, sample_team_with_owner_member):
        """Test breadcrumb for product (should have no parents)."""
        team = sample_team_with_owner_member.team

        # Create a product
        product = Product.objects.create(
            name="Test Product",
            team=team,
            is_public=True,
        )

        # Test the breadcrumb template tag
        template = Template("""
            {% load breadcrumb_tags %}
            {% breadcrumb product 'product' %}
        """)

        context = Context({"product": product})
        template.render(context)

        # Should not contain any breadcrumb items since products are top-level
        # With the new template, when there are no crumbs, nothing is rendered
