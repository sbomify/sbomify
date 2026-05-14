"""
Tests for permission consistency across all API endpoints.

This module tests that the appropriate API endpoints properly handle
authentication and public access in a consistent manner.
"""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product


@pytest.mark.django_db
class TestListEndpointPermissions:
    """Test that all list endpoints properly handle public vs private access."""

    def test_list_products_requires_auth(self, sample_team, sample_user):  # noqa: F811
        """Listing products requires authentication — no anonymous enumeration of public items."""
        Product.objects.create(name="Public Product", team=sample_team, is_public=True)
        Product.objects.create(name="Private Product", team=sample_team, is_public=False)

        client = Client()
        url = reverse("api-1:list_products")

        # No Authorization header → 401
        response = client.get(url)
        assert response.status_code == 401

        # Garbage bearer token → 401 (not silently downgraded to anonymous)
        response = client.get(url, HTTP_AUTHORIZATION="Bearer not-a-real-token")
        assert response.status_code == 401

    def test_list_components_requires_auth(self, sample_team, sample_product):  # noqa: F811
        """Listing components requires authentication — no anonymous enumeration of public items."""
        public_component = Component.objects.create(
            name="Public Component",
            team=sample_team,
            visibility=Component.Visibility.PUBLIC,
        )
        sample_product.components.add(public_component)

        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            visibility=Component.Visibility.PRIVATE,
        )
        sample_product.components.add(private_component)

        client = Client()
        url = reverse("api-1:list_components")

        # No Authorization header → 401
        response = client.get(url)
        assert response.status_code == 401

        # Garbage bearer token → 401 (not silently downgraded to anonymous)
        response = client.get(url, HTTP_AUTHORIZATION="Bearer not-a-real-token")
        assert response.status_code == 401

    def test_list_endpoints_authenticated_access(self, authenticated_api_client, sample_team, sample_product):  # noqa: F811
        """Test that authenticated users see their team's items."""
        client, access_token = authenticated_api_client

        product = Product.objects.create(name="Team Product", team=sample_team, is_public=False)
        component = Component.objects.create(
            name="Team Component",
            team=sample_team,
            visibility=Component.Visibility.PRIVATE,
        )
        product.components.add(component)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}

        response = client.get(reverse("api-1:list_products"), **headers)
        assert response.status_code == 200
        product_names = [item["name"] for item in response.json()["items"]]
        assert "Team Product" in product_names

        response = client.get(reverse("api-1:list_components"), **headers)
        assert response.status_code == 200
        component_names = [item["name"] for item in response.json()["items"]]
        assert "Team Component" in component_names


@pytest.mark.django_db
class TestGetEndpointPermissions:
    """Test that all get endpoints properly handle public vs private access."""

    def test_get_component_public_access(self, sample_team, sample_product):  # noqa: F811
        """Test that public components can be accessed without authentication."""
        public_component = Component.objects.create(
            name="Public Component",
            team=sample_team,
            visibility=Component.Visibility.PUBLIC,
        )
        sample_product.components.add(public_component)

        client = Client()
        url = reverse("api-1:get_component", kwargs={"component_id": public_component.id})

        response = client.get(url)
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Public Component"
        assert data["visibility"] == "public"

    def test_get_component_invalid_bearer_rejected(self, sample_team, sample_product):  # noqa: F811
        """A public-by-id endpoint must 401 a bad bearer instead of downgrading to anonymous."""
        public_component = Component.objects.create(
            name="Public Component",
            team=sample_team,
            visibility=Component.Visibility.PUBLIC,
        )
        sample_product.components.add(public_component)

        client = Client()
        url = reverse("api-1:get_component", kwargs={"component_id": public_component.id})

        response = client.get(url, HTTP_AUTHORIZATION="Bearer not-a-real-token")
        assert response.status_code == 401

    def test_get_component_private_access_denied(self, sample_team, sample_product):  # noqa: F811
        """Test that private components cannot be accessed without authentication."""
        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            visibility=Component.Visibility.PRIVATE,
        )
        sample_product.components.add(private_component)

        client = Client()
        url = reverse("api-1:get_component", kwargs={"component_id": private_component.id})

        response = client.get(url)
        assert response.status_code == 403

        data = response.json()
        assert "Authentication required for private items" in data["detail"]

    def test_get_component_authenticated_access(self, authenticated_api_client, sample_team, sample_product):  # noqa: F811
        """Test that authenticated users can access their team's private components."""
        client, access_token = authenticated_api_client

        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            visibility=Component.Visibility.PRIVATE,
        )
        sample_product.components.add(private_component)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}
        url = reverse("api-1:get_component", kwargs={"component_id": private_component.id})

        response = client.get(url, **headers)
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Private Component"
        assert data["visibility"] == "private"


@pytest.mark.django_db
class TestPermissionConsistencyPatterns:
    """Test that permission patterns are consistent across similar endpoints."""

    def test_public_product_access_consistency(self, sample_team, sample_product):  # noqa: F811
        """Test that all product-related endpoints consistently handle public access."""
        sample_product.is_public = True
        sample_product.save()

        client = Client()

        endpoints = [
            reverse("api-1:get_product", kwargs={"product_id": sample_product.id}),
            reverse("api-1:list_product_identifiers", kwargs={"product_id": sample_product.id}),
            reverse("api-1:list_product_links", kwargs={"product_id": sample_product.id}),
            reverse("api-1:download_product_sbom", kwargs={"product_id": sample_product.id}),
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code != 403, (
                f"Endpoint {endpoint} incorrectly requires authentication for public product"
            )

    def test_private_product_access_consistency(self, sample_team, sample_product):  # noqa: F811
        """Test that all product-related endpoints consistently require authentication for private products."""
        sample_product.is_public = False
        sample_product.save()

        client = Client()

        endpoints = [
            reverse("api-1:get_product", kwargs={"product_id": sample_product.id}),
            reverse("api-1:list_product_identifiers", kwargs={"product_id": sample_product.id}),
            reverse("api-1:list_product_links", kwargs={"product_id": sample_product.id}),
            reverse("api-1:download_product_sbom", kwargs={"product_id": sample_product.id}),
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 403, f"Endpoint {endpoint} should require authentication for private product"

    def test_error_message_consistency(self, sample_team, sample_product):  # noqa: F811
        """Test that error messages are consistent across endpoints."""
        sample_product.is_public = False
        sample_product.save()

        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            visibility=Component.Visibility.PRIVATE,
        )
        sample_product.components.add(private_component)

        client = Client()

        endpoints_and_expected_messages = [
            (
                reverse("api-1:get_product", kwargs={"product_id": sample_product.id}),
                "Authentication required for private items",
            ),
            (
                reverse("api-1:get_component", kwargs={"component_id": private_component.id}),
                "Authentication required for private items",
            ),
            (
                reverse("api-1:list_product_identifiers", kwargs={"product_id": sample_product.id}),
                "Authentication required for private items",
            ),
            (
                reverse("api-1:list_product_links", kwargs={"product_id": sample_product.id}),
                "Authentication required for private items",
            ),
        ]

        for endpoint, expected_message in endpoints_and_expected_messages:
            response = client.get(endpoint)
            assert response.status_code == 403
            data = response.json()
            assert expected_message in data["detail"], f"Endpoint {endpoint} has inconsistent error message"

    def test_authentication_decorator_consistency(self, sample_team):  # noqa: F811
        """Public per-id endpoints stay reachable without auth; list endpoints don't (enumeration ban)."""
        client = Client()

        public_product = Product.objects.create(name="Public Product", team=sample_team, is_public=True)
        public_component = Component.objects.create(
            name="Public Component",
            team=sample_team,
            visibility=Component.Visibility.PUBLIC,
        )
        public_product.components.add(public_component)

        public_endpoints = [
            reverse("api-1:get_product", kwargs={"product_id": public_product.id}),
            reverse("api-1:get_component", kwargs={"component_id": public_component.id}),
            reverse("api-1:list_product_identifiers", kwargs={"product_id": public_product.id}),
            reverse("api-1:list_product_links", kwargs={"product_id": public_product.id}),
        ]

        for endpoint in public_endpoints:
            response = client.get(endpoint)
            # Tight equality (rather than `!= 403`) so a regression to 401 or any
            # other non-success status is caught instead of silently passing.
            assert response.status_code == 200, (
                f"Endpoint {endpoint} must remain reachable without auth for public items "
                f"(got {response.status_code})"
            )

        for endpoint in (reverse("api-1:list_products"), reverse("api-1:list_components")):
            response = client.get(endpoint)
            assert response.status_code == 401, (
                f"Endpoint {endpoint} must require authentication — no anonymous enumeration"
            )
