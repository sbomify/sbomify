"""
Tests for permission consistency across all API endpoints.

This module tests that the appropriate API endpoints properly handle
authentication and public access in a consistent manner.
"""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Project


@pytest.mark.django_db
class TestListEndpointPermissions:
    """Test that all list endpoints properly handle public vs private access."""

    def test_list_products_public_access(self, sample_team, sample_user):  # noqa: F811
        """Test that public products can be listed without authentication."""
        # Create both public and private products
        public_product = Product.objects.create(
            name="Public Product",
            team=sample_team,
            is_public=True
        )
        private_product = Product.objects.create(
            name="Private Product",
            team=sample_team,
            is_public=False
        )

        client = Client()
        url = reverse("api-1:list_products")

        response = client.get(url)
        assert response.status_code == 200

        data = response.json()
        assert "items" in data
        assert "pagination" in data

        # Should only show public products
        product_names = [item["name"] for item in data["items"]]
        assert "Public Product" in product_names
        assert "Private Product" not in product_names

    def test_list_projects_public_access(self, sample_team, sample_product):  # noqa: F811
        """Test that public projects can be listed without authentication."""
        # Create both public and private projects
        public_project = Project.objects.create(
            name="Public Project",
            team=sample_team,
            product=sample_product,
            is_public=True
        )
        private_project = Project.objects.create(
            name="Private Project",
            team=sample_team,
            product=sample_product,
            is_public=False
        )

        client = Client()
        url = reverse("api-1:list_projects")

        response = client.get(url)
        assert response.status_code == 200

        data = response.json()
        assert "items" in data
        assert "pagination" in data

        # Should only show public projects
        project_names = [item["name"] for item in data["items"]]
        assert "Public Project" in project_names
        assert "Private Project" not in project_names

    def test_list_components_public_access(self, sample_team, sample_project):  # noqa: F811
        """Test that public components can be listed without authentication."""
        # Create both public and private components
        public_component = Component.objects.create(
            name="Public Component",
            team=sample_team,
            is_public=True
        )
        public_component.projects.add(sample_project)

        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            is_public=False
        )
        private_component.projects.add(sample_project)

        client = Client()
        url = reverse("api-1:list_components")

        response = client.get(url)
        assert response.status_code == 200

        data = response.json()
        assert "items" in data
        assert "pagination" in data

        # Should only show public components
        component_names = [item["name"] for item in data["items"]]
        assert "Public Component" in component_names
        assert "Private Component" not in component_names

    def test_list_endpoints_authenticated_access(self, authenticated_api_client, sample_team, sample_product, sample_project):  # noqa: F811
        """Test that authenticated users see their team's items."""
        client, access_token = authenticated_api_client

        # Create test items
        product = Product.objects.create(
            name="Team Product",
            team=sample_team,
            is_public=False
        )
        project = Project.objects.create(
            name="Team Project",
            team=sample_team,
            product=product,
            is_public=False
        )
        component = Component.objects.create(
            name="Team Component",
            team=sample_team,
            is_public=False
        )
        component.projects.add(project)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}

        # Test products endpoint
        response = client.get(reverse("api-1:list_products"), **headers)
        assert response.status_code == 200
        product_names = [item["name"] for item in response.json()["items"]]
        assert "Team Product" in product_names

        # Test projects endpoint
        response = client.get(reverse("api-1:list_projects"), **headers)
        assert response.status_code == 200
        project_names = [item["name"] for item in response.json()["items"]]
        assert "Team Project" in project_names

        # Test components endpoint
        response = client.get(reverse("api-1:list_components"), **headers)
        assert response.status_code == 200
        component_names = [item["name"] for item in response.json()["items"]]
        assert "Team Component" in component_names


@pytest.mark.django_db
class TestGetEndpointPermissions:
    """Test that all get endpoints properly handle public vs private access."""

    def test_get_component_public_access(self, sample_team, sample_project):  # noqa: F811
        """Test that public components can be accessed without authentication."""
        # Create public component
        public_component = Component.objects.create(
            name="Public Component",
            team=sample_team,
            is_public=True
        )
        public_component.projects.add(sample_project)

        client = Client()
        url = reverse("api-1:get_component", kwargs={"component_id": public_component.id})

        response = client.get(url)
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Public Component"
        assert data["is_public"] is True

    def test_get_component_private_access_denied(self, sample_team, sample_project):  # noqa: F811
        """Test that private components cannot be accessed without authentication."""
        # Create private component
        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            is_public=False
        )
        private_component.projects.add(sample_project)

        client = Client()
        url = reverse("api-1:get_component", kwargs={"component_id": private_component.id})

        response = client.get(url)
        assert response.status_code == 403

        data = response.json()
        assert "Authentication required for private items" in data["detail"]

    def test_get_component_authenticated_access(self, authenticated_api_client, sample_team, sample_project):  # noqa: F811
        """Test that authenticated users can access their team's private components."""
        client, access_token = authenticated_api_client

        # Create private component
        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            is_public=False
        )
        private_component.projects.add(sample_project)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse("api-1:get_component", kwargs={"component_id": private_component.id})

        response = client.get(url, **headers)
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Private Component"
        assert data["is_public"] is False


@pytest.mark.django_db
class TestPermissionConsistencyPatterns:
    """Test that permission patterns are consistent across similar endpoints."""

    def test_public_product_access_consistency(self, sample_team, sample_product):  # noqa: F811
        """Test that all product-related endpoints consistently handle public access."""
        # Make product public
        sample_product.is_public = True
        sample_product.save()

        client = Client()

        # Test all product endpoints that should allow public access
        endpoints = [
            reverse("api-1:get_product", kwargs={"product_id": sample_product.id}),
            reverse("api-1:list_product_identifiers", kwargs={"product_id": sample_product.id}),
            reverse("api-1:list_product_links", kwargs={"product_id": sample_product.id}),
            reverse("api-1:download_product_sbom", kwargs={"product_id": sample_product.id}),
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            # All should either return 200 or 500 (if no data), but not 403
            assert response.status_code != 403, f"Endpoint {endpoint} incorrectly requires authentication for public product"

    def test_private_product_access_consistency(self, sample_team, sample_product):  # noqa: F811
        """Test that all product-related endpoints consistently require authentication for private products."""
        # Make product private
        sample_product.is_public = False
        sample_product.save()

        client = Client()

        # Test all product endpoints that should require authentication for private access
        endpoints = [
            reverse("api-1:get_product", kwargs={"product_id": sample_product.id}),
            reverse("api-1:list_product_identifiers", kwargs={"product_id": sample_product.id}),
            reverse("api-1:list_product_links", kwargs={"product_id": sample_product.id}),
            reverse("api-1:download_product_sbom", kwargs={"product_id": sample_product.id}),
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            # All should return 403 for private items
            assert response.status_code == 403, f"Endpoint {endpoint} should require authentication for private product"

    def test_error_message_consistency(self, sample_team, sample_product, sample_project):  # noqa: F811
        """Test that error messages are consistent across endpoints."""
        # Create private items
        sample_product.is_public = False
        sample_product.save()

        sample_project.is_public = False
        sample_project.save()

        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            is_public=False
        )
        private_component.projects.add(sample_project)

        client = Client()

        # Test that all endpoints return consistent error messages
        endpoints_and_expected_messages = [
            (reverse("api-1:get_product", kwargs={"product_id": sample_product.id}), "Authentication required for private items"),
            (reverse("api-1:get_project", kwargs={"project_id": sample_project.id}), "Authentication required for private items"),
            (reverse("api-1:get_component", kwargs={"component_id": private_component.id}), "Authentication required for private items"),
            (reverse("api-1:list_product_identifiers", kwargs={"product_id": sample_product.id}), "Authentication required for private items"),
            (reverse("api-1:list_product_links", kwargs={"product_id": sample_product.id}), "Authentication required for private items"),
        ]

        for endpoint, expected_message in endpoints_and_expected_messages:
            response = client.get(endpoint)
            assert response.status_code == 403
            data = response.json()
            assert expected_message in data["detail"], f"Endpoint {endpoint} has inconsistent error message"

    def test_authentication_decorator_consistency(self, sample_team):  # noqa: F811
        """Test that endpoints that should allow public access all use the same authentication pattern."""
        client = Client()

        # Create public items
        public_product = Product.objects.create(
            name="Public Product",
            team=sample_team,
            is_public=True
        )
        public_project = Project.objects.create(
            name="Public Project",
            team=sample_team,
            product=public_product,
            is_public=True
        )
        public_component = Component.objects.create(
            name="Public Component",
            team=sample_team,
            is_public=True
        )
        public_component.projects.add(public_project)

        # All these endpoints should work without authentication when items are public
        public_endpoints = [
            reverse("api-1:get_product", kwargs={"product_id": public_product.id}),
            reverse("api-1:get_project", kwargs={"project_id": public_project.id}),
            reverse("api-1:get_component", kwargs={"component_id": public_component.id}),
            reverse("api-1:list_products"),
            reverse("api-1:list_projects"),
            reverse("api-1:list_components"),
            reverse("api-1:list_product_identifiers", kwargs={"product_id": public_product.id}),
            reverse("api-1:list_product_links", kwargs={"product_id": public_product.id}),
        ]

        for endpoint in public_endpoints:
            response = client.get(endpoint)
            # Should either return 200 or 500 (if no data), but not 403
            assert response.status_code != 403, f"Endpoint {endpoint} incorrectly requires authentication for public items"