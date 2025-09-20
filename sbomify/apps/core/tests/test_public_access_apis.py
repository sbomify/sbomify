"""
Tests for public access to API endpoints.

This module tests that the appropriate API endpoints allow public access
when items are marked as public, and properly reject access when items
are private.
"""

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Release


@pytest.mark.django_db
class TestPublicReleaseAccess:
    """Test public access to release endpoints."""

    def test_list_releases_public_product_no_auth(self, sample_product):  # noqa: F811
        """Test that releases can be listed for public products without authentication."""
        # Make product public
        sample_product.is_public = True
        sample_product.save()

        # Create test releases
        release1 = Release.objects.create(product=sample_product, name="v1.0.0")
        release2 = Release.objects.create(product=sample_product, name="v2.0.0")

        client = Client()
        url = reverse("api-1:list_all_releases") + f"?product_id={sample_product.id}"

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "pagination" in data
        # Should have 3 releases: 2 manual + 1 automatic "latest" release
        assert len(data["items"]) == 3

        release_names = [r["name"] for r in data["items"]]
        release_ids = [r["id"] for r in data["items"]]

        # Verify the manual releases are present
        assert release1.id in release_ids
        assert release2.id in release_ids
        assert "v1.0.0" in release_names
        assert "v2.0.0" in release_names

        # Verify the automatic latest release was created
        assert "latest" in release_names

    def test_list_releases_private_product_no_auth(self, sample_product):  # noqa: F811
        """Test that releases cannot be listed for private products without authentication."""
        # Ensure product is private
        sample_product.is_public = False
        sample_product.save()

        client = Client()
        url = reverse("api-1:list_all_releases") + f"?product_id={sample_product.id}"

        response = client.get(url)

        assert response.status_code == 403
        data = response.json()
        assert "No current team selected" in data["detail"]

    def test_list_releases_private_product_with_auth(self, sample_product, authenticated_api_client):  # noqa: F811
        """Test that releases can be listed for private products with proper authentication."""
        # Ensure product is private
        sample_product.is_public = False
        sample_product.save()

        # Create test releases
        Release.objects.create(product=sample_product, name="v1.0.0")

        client, access_token = authenticated_api_client
        url = reverse("api-1:list_all_releases") + f"?product_id={sample_product.id}"

        response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {access_token.encoded_token}")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "pagination" in data
        assert len(data["items"]) >= 1  # At least our manual release


@pytest.mark.django_db
class TestPublicSBOMAccess:
    """Test public access to SBOM endpoints."""

    def test_list_component_sboms_public_component_no_auth(self, sample_component, sample_sbom):  # noqa: F811
        """Test that SBOMs can be listed for public components without authentication."""
        # Make component public
        sample_component.is_public = True
        sample_component.save()

        client = Client()
        url = reverse("api-1:list_component_sboms", kwargs={"component_id": sample_component.id})

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) >= 1

        # Verify our SBOM is in the response
        sbom_ids = [item["sbom"]["id"] for item in data["items"]]
        assert sample_sbom.id in sbom_ids

    def test_list_component_sboms_private_component_no_auth(self, sample_component, sample_sbom):  # noqa: F811
        """Test that SBOMs cannot be listed for private components without authentication."""
        # Ensure component is private
        sample_component.is_public = False
        sample_component.save()

        client = Client()
        url = reverse("api-1:list_component_sboms", kwargs={"component_id": sample_component.id})

        response = client.get(url)

        assert response.status_code == 403
        data = response.json()
        assert "Authentication required for private items" in data["detail"]

    def test_list_component_sboms_private_component_with_auth(
        self,
        sample_component,
        sample_sbom,
        authenticated_api_client,  # noqa: F811
    ):
        """Test that SBOMs can be listed for private components with proper authentication."""
        # Ensure component is private
        sample_component.is_public = False
        sample_component.save()

        client, access_token = authenticated_api_client
        url = reverse("api-1:list_component_sboms", kwargs={"component_id": sample_component.id})

        response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {access_token.encoded_token}")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) >= 1


@pytest.mark.django_db
class TestPublicDocumentAccess:
    """Test public access to document endpoints."""

    @pytest.fixture
    def sample_document(self, sample_component):  # noqa: F811
        """Create a sample document for testing."""
        from sbomify.apps.documents.models import Document

        document = Document.objects.create(
            name="Test Document",
            component=sample_component,
            document_type="specification",
            description="A test document",
        )
        return document

    def test_list_component_documents_public_component_no_auth(self, sample_component, sample_document):  # noqa: F811
        """Test that documents can be listed for public components without authentication."""
        # Make component public
        sample_component.is_public = True
        sample_component.save()

        client = Client()
        url = reverse("api-1:list_component_documents", kwargs={"component_id": sample_component.id})

        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) >= 1

        # Verify our document is in the response
        document_ids = [item["document"]["id"] for item in data["items"]]
        assert sample_document.id in document_ids

    def test_list_component_documents_private_component_no_auth(self, sample_component, sample_document):  # noqa: F811
        """Test that documents cannot be listed for private components without authentication."""
        # Ensure component is private
        sample_component.is_public = False
        sample_component.save()

        client = Client()
        url = reverse("api-1:list_component_documents", kwargs={"component_id": sample_component.id})

        response = client.get(url)

        assert response.status_code == 403
        data = response.json()
        assert "Authentication required for private items" in data["detail"]

    def test_list_component_documents_private_component_with_auth(
        self,
        sample_component,
        sample_document,
        authenticated_api_client,  # noqa: F811
    ):
        """Test that documents can be listed for private components with proper authentication."""
        # Ensure component is private
        sample_component.is_public = False
        sample_component.save()

        client, access_token = authenticated_api_client
        url = reverse("api-1:list_component_documents", kwargs={"component_id": sample_component.id})

        response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {access_token.encoded_token}")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) >= 1


@pytest.mark.django_db
class TestPublicAccessConsistency:
    """Test that public access behavior is consistent across all endpoints."""

    def test_product_identifiers_public_access(self, sample_product):  # noqa: F811
        """Test that product identifiers work for public products."""
        # Make product public
        sample_product.is_public = True
        sample_product.save()

        client = Client()
        url = reverse("api-1:list_product_identifiers", kwargs={"product_id": sample_product.id})

        response = client.get(url)
        assert response.status_code == 200

    def test_product_links_public_access(self, sample_product):  # noqa: F811
        """Test that product links work for public products."""
        # Make product public
        sample_product.is_public = True
        sample_product.save()

        client = Client()
        url = reverse("api-1:list_product_links", kwargs={"product_id": sample_product.id})

        response = client.get(url)
        assert response.status_code == 200

    def test_private_items_require_auth(self, sample_product, sample_component):  # noqa: F811
        """Test that private items consistently require authentication."""
        # Ensure items are private
        sample_product.is_public = False
        sample_product.save()
        sample_component.is_public = False
        sample_component.save()

        client = Client()

        # Test product identifiers
        url = reverse("api-1:list_product_identifiers", kwargs={"product_id": sample_product.id})
        response = client.get(url)
        assert response.status_code == 403

        # Test product links
        url = reverse("api-1:list_product_links", kwargs={"product_id": sample_product.id})
        response = client.get(url)
        assert response.status_code == 403

        # Test releases
        url = reverse("api-1:list_all_releases") + f"?product_id={sample_product.id}"
        response = client.get(url)
        assert response.status_code == 403

        # Test component SBOMs
        url = reverse("api-1:list_component_sboms", kwargs={"component_id": sample_component.id})
        response = client.get(url)
        assert response.status_code == 403

        # Test component documents
        url = reverse("api-1:list_component_documents", kwargs={"component_id": sample_component.id})
        response = client.get(url)
        assert response.status_code == 403
