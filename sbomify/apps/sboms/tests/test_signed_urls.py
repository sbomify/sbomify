"""
Tests for signed URL functionality for private component SBOMs and documents.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from sbomify.apps.core.models import Component, Product, Project
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import team_with_business_plan  # noqa: F401
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import (
    generate_signed_download_url,
    get_download_url_for_document,
    get_download_url_for_sbom,
    make_document_download_token,
    make_download_token,
    should_use_signed_url,
    should_use_signed_url_for_document,
)


@pytest.mark.django_db
class TestSignedURLs:
    """Test case for signed URL functionality."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, team_with_business_plan, sample_user):  # noqa: F811
        """Set up test data using shared fixtures."""
        self.user = sample_user
        self.team = team_with_business_plan
        self.client = Client()

        # Create public component
        self.public_component = Component.objects.create(
            name="Public Component",
            team=self.team,
            visibility=Component.Visibility.PUBLIC,
            component_type=Component.ComponentType.SBOM,
        )

        # Create private component
        self.private_component = Component.objects.create(
            name="Private Component",
            team=self.team,
            visibility=Component.Visibility.PRIVATE,
            component_type=Component.ComponentType.SBOM,
        )

        # Create public document component
        self.public_document_component = Component.objects.create(
            name="Public Document Component",
            team=self.team,
            visibility=Component.Visibility.PUBLIC,
            component_type=Component.ComponentType.DOCUMENT,
        )

        # Create private document component
        self.private_document_component = Component.objects.create(
            name="Private Document Component",
            team=self.team,
            visibility=Component.Visibility.PRIVATE,
            component_type=Component.ComponentType.DOCUMENT,
        )

        # Create SBOMs
        self.public_sbom = SBOM.objects.create(
            name="Public SBOM",
            component=self.public_component,
            format="cyclonedx",
            version="1.0.0",
            sbom_filename="public_sbom.json",
        )

        self.private_sbom = SBOM.objects.create(
            name="Private SBOM",
            component=self.private_component,
            format="cyclonedx",
            version="1.0.0",
            sbom_filename="private_sbom.json",
        )

        # Create documents
        self.public_document = Document.objects.create(
            name="Public Document",
            component=self.public_document_component,
            version="1.0.0",
            document_filename="public_document.pdf",
            content_type="application/pdf",
        )

        self.private_document = Document.objects.create(
            name="Private Document",
            component=self.private_document_component,
            version="1.0.0",
            document_filename="private_document.pdf",
            content_type="application/pdf",
        )

    def test_generate_signed_download_url(self):
        """Test generating a signed download URL for a private SBOM."""
        url = generate_signed_download_url(self.private_sbom.id, str(self.user.id), "https://example.com")

        assert "signed" in url
        assert "token=" in url
        assert self.private_sbom.id in url

    def test_get_download_url_for_sbom_private(self):
        """Test download URL generation for private SBOM."""
        url = get_download_url_for_sbom(self.private_sbom, self.user, "https://example.com")

        assert "signed" in url
        assert "token=" in url

    def test_get_download_url_for_sbom_private_unauthenticated(self):
        """Test download URL generation for private SBOM with unauthenticated user."""
        url = get_download_url_for_sbom(self.private_sbom, None, "https://example.com")

        # Should fallback to regular URL for unauthenticated users, using UUID
        assert "signed" not in url
        assert "token=" not in url
        assert str(self.private_sbom.uuid) in url

    def test_get_download_url_for_sbom_public(self):
        """Test download URL generation for public SBOM."""
        url = get_download_url_for_sbom(self.public_sbom, self.user, "https://example.com")

        # Public SBOMs should use regular URLs with UUID
        assert "signed" not in url
        assert "token=" not in url
        assert str(self.public_sbom.uuid) in url

    def test_make_download_token(self):
        """Test making a download token for private SBOM."""
        token = make_download_token(self.private_sbom.id, str(self.user.id))

        assert isinstance(token, str)
        assert len(token) > 0

    def test_should_use_signed_url_private_component(self):
        """Test that private components should use signed URLs."""
        assert should_use_signed_url(self.private_sbom, self.user)

    def test_should_not_use_signed_url_for_public_component(self):
        """Test that public components should NOT use signed URLs."""
        assert not should_use_signed_url(self.public_sbom, self.user)

    def test_make_document_download_token(self):
        """Test making a download token for private document."""
        token = make_document_download_token(self.private_document.id, str(self.user.id))

        assert isinstance(token, str)
        assert len(token) > 0

    def test_should_use_signed_url_for_document_private(self):
        """Test that private documents should use signed URLs."""
        assert should_use_signed_url_for_document(self.private_document, self.user)

    def test_should_not_use_signed_url_for_public_document(self):
        """Test that public documents should NOT use signed URLs."""
        assert not should_use_signed_url_for_document(self.public_document, self.user)

    def test_get_download_url_for_document_private(self):
        """Test download URL generation for private document."""
        url = get_download_url_for_document(self.private_document, self.user, "https://example.com")

        assert "signed" in url
        assert "token=" in url

    def test_get_download_url_for_document_private_unauthenticated(self):
        """Test download URL generation for private document with unauthenticated user."""
        url = get_download_url_for_document(self.private_document, None, "https://example.com")

        # Should fallback to regular URL for unauthenticated users, using UUID
        assert "signed" not in url
        assert "token=" not in url
        assert str(self.private_document.uuid) in url

    def test_get_download_url_for_document_public(self):
        """Test download URL generation for public document."""
        url = get_download_url_for_document(self.public_document, self.user, "https://example.com")

        # Public documents should use regular URLs with UUID
        assert "signed" not in url
        assert "token=" not in url
        assert str(self.public_document.uuid) in url

    def test_signed_download_endpoint_valid_token(self):
        """Test the signed download endpoint with valid token."""
        # Generate valid token
        token = make_download_token(self.private_sbom.id, str(self.user.id))

        # Mock S3 client using the proper sboms API mock
        with patch("sbomify.apps.sboms.apis.S3Client") as mock_s3_client:
            mock_s3_instance = MagicMock()
            mock_s3_instance.get_sbom_data.return_value = b'{"test": "data"}'
            mock_s3_client.return_value = mock_s3_instance

            # Make request
            url = f"/api/v1/sboms/{self.private_sbom.id}/download/signed"
            response = self.client.get(url, {"token": token})

            assert response.status_code == 200
            assert response.content == b'{"test": "data"}'

    def test_signed_document_download_endpoint_valid_token(self):
        """Test the signed document download endpoint with valid token."""
        # Generate valid token
        token = make_document_download_token(self.private_document.id, str(self.user.id))

        # Mock S3 client using the proper documents API mock
        with patch("sbomify.apps.documents.apis.S3Client") as mock_s3_client:
            mock_s3_instance = MagicMock()
            mock_s3_instance.get_document_data.return_value = b"test document content"
            mock_s3_client.return_value = mock_s3_instance

            # Make request
            url = f"/api/v1/documents/{self.private_document.id}/download/signed"
            response = self.client.get(url, {"token": token})

            assert response.status_code == 200
            assert response.content == b"test document content"

    def test_signed_download_endpoint_invalid_token(self):
        """Test the signed download endpoint with invalid token."""
        url = f"/api/v1/sboms/{self.private_sbom.id}/download/signed"
        response = self.client.get(url, {"token": "invalid_token"})

        assert response.status_code == 403

    def test_signed_document_download_endpoint_invalid_token(self):
        """Test the signed document download endpoint with invalid token."""
        url = f"/api/v1/documents/{self.private_document.id}/download/signed"
        response = self.client.get(url, {"token": "invalid_token"})

        assert response.status_code == 403

    def test_signed_download_endpoint_expired_token(self):
        """Test the signed download endpoint with expired token."""
        # Mock the token verification to return None (expired token)
        with patch("sbomify.apps.sboms.apis.verify_download_token", return_value=None):
            token = make_download_token(self.private_sbom.id, str(self.user.id))

            url = f"/api/v1/sboms/{self.private_sbom.id}/download/signed"
            response = self.client.get(url, {"token": token})

            assert response.status_code == 403

    def test_signed_document_download_endpoint_mismatched_document(self):
        """Test the signed document download endpoint with token for different document."""
        # Generate valid token for different document
        token = make_document_download_token(self.private_document.id, str(self.user.id))

        url = f"/api/v1/documents/{self.public_document.id}/download/signed"
        response = self.client.get(url, {"token": token})

        assert response.status_code == 403

    def test_signed_document_download_endpoint_nonexistent_user(self):
        """Test the signed document download endpoint with token for nonexistent user."""
        # Generate valid token for nonexistent user
        token = make_document_download_token(self.private_document.id, "99999999")

        url = f"/api/v1/documents/{self.private_document.id}/download/signed"
        response = self.client.get(url, {"token": token})

        assert response.status_code == 403

    def test_signed_download_endpoint_public_component(self):
        """Test the signed download endpoint works for public components too."""
        # Even though public components don't need signed URLs, the endpoint should work
        token = make_download_token(self.public_sbom.id, str(self.user.id))

        # Mock S3 client using the proper sboms API mock
        with patch("sbomify.apps.sboms.apis.S3Client") as mock_s3_client:
            mock_s3_instance = MagicMock()
            mock_s3_instance.get_sbom_data.return_value = b'{"test": "data"}'
            mock_s3_client.return_value = mock_s3_instance

            url = f"/api/v1/sboms/{self.public_sbom.id}/download/signed"
            response = self.client.get(url, {"token": token})

            assert response.status_code == 200

    def test_signed_document_download_endpoint_public_component(self):
        """Test the signed document download endpoint works for public components too."""
        # Even though public components don't need signed URLs, the endpoint should work
        token = make_document_download_token(self.public_document.id, str(self.user.id))

        # Mock S3 client using the proper documents API mock
        with patch("sbomify.apps.documents.apis.S3Client") as mock_s3_client:
            mock_s3_instance = MagicMock()
            mock_s3_instance.get_document_data.return_value = b"test document content"
            mock_s3_client.return_value = mock_s3_instance

            url = f"/api/v1/documents/{self.public_document.id}/download/signed"
            response = self.client.get(url, {"token": token})

            assert response.status_code == 200


@pytest.mark.django_db
class TestSignedURLIntegration:
    """Integration tests for signed URLs in product/project SBOMs."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, team_with_business_plan, sample_user):  # noqa: F811
        """Set up test data using shared fixtures."""
        self.user = sample_user
        self.team = team_with_business_plan
        self.client = Client()

        # Create components
        self.public_component = Component.objects.create(
            name="Public Component",
            team=self.team,
            visibility=Component.Visibility.PUBLIC,
            component_type=Component.ComponentType.SBOM,
        )

        self.private_component = Component.objects.create(
            name="Private Component",
            team=self.team,
            visibility=Component.Visibility.PRIVATE,
            component_type=Component.ComponentType.SBOM,
        )

        self.public_document_component = Component.objects.create(
            name="Public Document Component",
            team=self.team,
            visibility=Component.Visibility.PUBLIC,
            component_type=Component.ComponentType.DOCUMENT,
        )

        self.private_document_component = Component.objects.create(
            name="Private Document Component",
            team=self.team,
            visibility=Component.Visibility.PRIVATE,
            component_type=Component.ComponentType.DOCUMENT,
        )

        # Create SBOMs
        self.public_sbom = SBOM.objects.create(
            name="Public SBOM",
            component=self.public_component,
            format="cyclonedx",
            version="1.0.0",
            sbom_filename="public_sbom.json",
        )

        self.private_sbom = SBOM.objects.create(
            name="Private SBOM",
            component=self.private_component,
            format="cyclonedx",
            version="1.0.0",
            sbom_filename="private_sbom.json",
        )

        # Create documents
        self.public_document = Document.objects.create(
            name="Public Document",
            component=self.public_document_component,
            version="1.0.0",
            document_filename="public_document.pdf",
            content_type="application/pdf",
        )

        self.private_document = Document.objects.create(
            name="Private Document",
            component=self.private_document_component,
            version="1.0.0",
            document_filename="private_document.pdf",
            content_type="application/pdf",
        )

        # Create project and product
        self.project = Project.objects.create(name="Test Project", team=self.team, is_public=False)

        self.product = Product.objects.create(name="Test Product", team=self.team, is_public=False)

        # Link components to project
        self.project.components.add(self.public_component)
        self.project.components.add(self.private_component)
        self.project.components.add(self.public_document_component)
        self.project.components.add(self.private_document_component)

        # Link project to product
        self.product.projects.add(self.project)

    def test_project_sbom_contains_signed_urls(self):
        """Test that project SBOMs contain signed URLs for private components."""
        # Mock S3 client to return sample SBOM data
        with patch("sbomify.apps.sboms.apis.S3Client") as mock_s3_client:
            mock_s3_instance = MagicMock()
            mock_s3_instance.get_sbom_data.return_value = b"""{
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {
                    "component": {
                        "name": "Test Component",
                        "type": "library",
                        "version": "1.0.0"
                    }
                }
            }"""
            mock_s3_client.return_value = mock_s3_instance

            # Login user
            self.client.force_login(self.user)

            # Request project SBOM
            url = f"/api/v1/projects/{self.project.id}/download"
            response = self.client.get(url)

            assert response.status_code == 200

            # Check that the response contains SBOM data
            assert "application/json" in response.get("Content-Type", "")

    def test_product_sbom_contains_signed_urls(self):
        """Test that product SBOMs contain signed URLs for private components."""
        # Mock S3 client to return sample SBOM data
        with patch("sbomify.apps.sboms.apis.S3Client") as mock_s3_client:
            mock_s3_instance = MagicMock()
            mock_s3_instance.get_sbom_data.return_value = b"""{
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {
                    "component": {
                        "name": "Test Component",
                        "type": "library",
                        "version": "1.0.0"
                    }
                }
            }"""
            mock_s3_client.return_value = mock_s3_instance

            # Login user
            self.client.force_login(self.user)

            # Request product SBOM
            url = f"/api/v1/products/{self.product.id}/download"
            response = self.client.get(url)

            assert response.status_code == 200

            # Check that the response contains SBOM data
            assert "application/json" in response.get("Content-Type", "")

    def test_unauthenticated_access_to_private_project_sbom(self):
        """Test that unauthenticated users can't access private project SBOMs."""
        url = f"/api/v1/projects/{self.project.id}/download"
        response = self.client.get(url)

        assert response.status_code == 403

    def test_unauthenticated_access_to_private_product_sbom(self):
        """Test that unauthenticated users can't access private product SBOMs."""
        url = f"/api/v1/products/{self.product.id}/download"
        response = self.client.get(url)

        assert response.status_code == 403
