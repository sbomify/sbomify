import json
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase

from sbomify.apps.core.apis import list_release_artifacts
from sbomify.apps.core.models import Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.shared_fixtures import (
    get_api_headers,
)
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM, Component
from sbomify.apps.teams.models import Team

User = get_user_model()


class TestReleaseArtifactsAPI(TestCase):
    """Test release artifacts API to ensure correct version field mapping."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()

        # Create test team
        self.team = Team.objects.create(key="test-team", name="Test Team")

        # Create test product
        self.product = Product.objects.create(team=self.team, name="Test Product", is_public=True)

        # Create test release
        self.release = Release.objects.create(product=self.product, name="v1.0.0", description="Test release")

        # Create test component
        self.component = Component.objects.create(
            team=self.team, name="test-component", component_type=Component.ComponentType.SBOM, is_public=True
        )

        # Create test SBOM with different version and format_version
        self.sbom = SBOM.objects.create(
            name="test-sbom",
            version="sha256:abc123def456",  # Actual SBOM version
            format="cyclonedx",
            format_version="1.5",  # CDX format version
            component=self.component,
            source="test",
        )

        # Add SBOM to release as artifact
        self.release_artifact = ReleaseArtifact.objects.create(release=self.release, sbom=self.sbom)

    def test_sbom_version_returns_actual_version_not_format_version(self):
        """Test that sbom_version returns actual version not format version."""
        # Clear existing artifacts from the release
        ReleaseArtifact.objects.filter(release=self.release).delete()

        # Create an SBOM with both format version and actual version
        sbom = SBOM.objects.create(
            name="test-sbom-unique",
            component=self.component,
            format="CycloneDX",
            format_version="1.4",  # This is the format version
            version="2.0.1",  # This is the actual version
        )

        # Create a release artifact
        ReleaseArtifact.objects.create(release=self.release, sbom=sbom)

        # Make API request
        request = self.factory.get(f"/api/v1/releases/{self.release.id}/artifacts?mode=existing&page=1&page_size=15")
        request.user = None

        # Call the API function directly
        response_data = list_release_artifacts(request, str(self.release.id), mode="existing")

        # Should return a dict with items and pagination
        self.assertIsInstance(response_data, dict)
        self.assertIn("items", response_data)
        self.assertIn("pagination", response_data)
        self.assertEqual(len(response_data["items"]), 1)

        artifact = response_data["items"][0]
        self.assertEqual(artifact["sbom_version"], "2.0.1")  # Should be actual version, not format version
        self.assertEqual(artifact["sbom_format"], "CycloneDX")  # Format should still be available

    def test_empty_sbom_version_returns_empty_string(self):
        """Test that empty sbom version returns empty string."""
        # Clear existing artifacts from the release
        ReleaseArtifact.objects.filter(release=self.release).delete()

        # Create an SBOM with empty version
        sbom = SBOM.objects.create(
            name="test-sbom-empty",
            component=self.component,
            format="CycloneDX",
            format_version="1.4",
            version="",  # Empty version
        )

        # Create a release artifact
        ReleaseArtifact.objects.create(release=self.release, sbom=sbom)

        # Make API request
        request = self.factory.get(f"/api/v1/releases/{self.release.id}/artifacts?mode=existing&page=1&page_size=15")
        request.user = None

        response_data = list_release_artifacts(request, str(self.release.id), mode="existing")

        # Should return a dict with items and pagination
        self.assertIsInstance(response_data, dict)
        self.assertIn("items", response_data)

        # Find the empty version artifact
        empty_artifact = None
        for artifact in response_data["items"]:
            if artifact["artifact_name"] == "test-sbom-empty":
                empty_artifact = artifact
                break

        self.assertIsNotNone(empty_artifact)
        self.assertEqual(empty_artifact["sbom_version"], "")  # Should be empty string for None version

    def test_component_slug_in_response(self):
        """Test that component_slug is included in release artifact response."""
        # Make API request
        request = self.factory.get(f"/api/v1/releases/{self.release.id}/artifacts?mode=existing&page=1&page_size=15")
        request.user = None

        response_data = list_release_artifacts(request, str(self.release.id), mode="existing")

        self.assertIsInstance(response_data, dict)
        self.assertIn("items", response_data)

        artifact = response_data["items"][0]
        # Component should have a slug (it's auto-generated from name)
        # Since we didn't specify slug in setUp, we expect it to be derived from name "test-component"
        # However, checking if the field exists is the key here
        self.assertIn("component_slug", artifact)
        # We can also check that it's a string given the component has a name
        # Depending on how logic works, it might be None if component has no slug,
        # but in our test we want to ensure the field is present.


@pytest.mark.django_db
class TestAddArtifactsToReleaseAPI:
    """Test the add_artifacts_to_release API endpoint with API token authentication.

    This tests the fix for the 403 Forbidden bug where API token-based access
    was incorrectly denied due to _get_user_team_id() returning the wrong team.
    Also tests 409 Conflict behavior for duplicate artifacts.
    """

    @pytest.fixture(autouse=True)
    def setup_test_data(self, team_with_business_plan: Team, sample_user: User) -> None:
        """Set up test data using shared fixtures."""
        self.team = team_with_business_plan
        self.user = sample_user

        # Create product
        self.product = Product.objects.create(name="Test Product", team=self.team, is_public=False)

        # Create release (not latest - we can add artifacts to non-latest releases)
        self.release = Release.objects.create(name="v1.0.0", product=self.product, is_latest=False, is_prerelease=False)

        # Create component
        self.component = Component.objects.create(name="Test Component", team=self.team, visibility=Component.Visibility.PRIVATE)

        # Create SBOM
        self.sbom = SBOM.objects.create(name="Test SBOM", component=self.component, format="cyclonedx", version="1.0.0")

    def test_add_artifact_with_api_token_succeeds(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding an artifact with API token authentication succeeds.

        This tests the fix for the access control bug where _get_user_team_id()
        was returning the wrong team for API token requests.
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        payload = {"sbom_id": str(self.sbom.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.content}"
        data = json.loads(response.content)
        assert data["artifact_type"] == "sbom"
        assert data["artifact_name"] == "Test SBOM"

        # Verify artifact was created
        assert ReleaseArtifact.objects.filter(release=self.release, sbom=self.sbom).exists()

    def test_add_duplicate_artifact_returns_409_conflict(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding a duplicate artifact returns 409 Conflict.

        This tests the RESTful behavior where trying to add an artifact
        that already exists in the release returns 409 Conflict.
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # First, add the artifact
        ReleaseArtifact.objects.create(release=self.release, sbom=self.sbom)

        # Try to add the same artifact again
        payload = {"sbom_id": str(self.sbom.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.content}"
        data = json.loads(response.content)
        assert "already in this release" in data["detail"]
        assert data["error_code"] == "DUPLICATE_ARTIFACT"

    def test_add_artifact_unauthenticated_returns_403(self) -> None:
        """Test that adding an artifact without authentication returns 403."""
        client = Client()

        payload = {"sbom_id": str(self.sbom.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 403

    def test_add_artifact_to_latest_release_returns_400(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding an artifact to a 'latest' release returns 400.

        Latest releases are auto-managed and cannot have artifacts added manually.
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Create a latest release
        latest_release = Release.objects.create(
            name="latest", product=self.product, is_latest=True, is_prerelease=False
        )

        payload = {"sbom_id": str(self.sbom.id)}

        response = client.post(
            f"/api/v1/releases/{latest_release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "latest" in data["detail"].lower()

    def test_add_artifact_from_different_team_returns_403(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding an artifact from a different team returns 403."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Create a different team with a component and SBOM
        other_team = Team.objects.create(name="Other Team")
        other_component = Component.objects.create(name="Other Component", team=other_team)
        other_sbom = SBOM.objects.create(
            name="Other SBOM", component=other_component, format="cyclonedx", version="1.0.0"
        )

        payload = {"sbom_id": str(other_sbom.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 403
        data = json.loads(response.content)
        # Generic error to avoid information disclosure
        assert data["detail"] == "Access denied"

    def test_add_duplicate_document_returns_409_conflict(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that adding a duplicate document returns 409 Conflict.

        This tests the RESTful behavior for documents (same as SBOMs).
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Create a document
        document = Document.objects.create(
            name="Test Document",
            component=self.component,
            document_type="attestation",
            version="1.0.0",
        )

        # First, add the document to release
        ReleaseArtifact.objects.create(release=self.release, document=document)

        # Try to add the same document again
        payload = {"document_id": str(document.id)}

        response = client.post(
            f"/api/v1/releases/{self.release.id}/artifacts",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.content}"
        data = json.loads(response.content)
        assert "already in this release" in data["detail"]
        assert data["error_code"] == "DUPLICATE_ARTIFACT"

    def test_remove_artifact_with_api_token_succeeds(self, authenticated_api_client: tuple[Client, Any]) -> None:
        """Test that removing an artifact with API token authentication succeeds.

        This tests that the access control fix also works for remove_artifact_from_release.
        """
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add artifact to release first
        artifact = ReleaseArtifact.objects.create(release=self.release, sbom=self.sbom)

        response = client.delete(
            f"/api/v1/releases/{self.release.id}/artifacts/{artifact.id}",
            **headers,
        )

        assert response.status_code == 204, f"Expected 204, got {response.status_code}: {response.content}"

        # Verify artifact was removed
        assert not ReleaseArtifact.objects.filter(id=artifact.id).exists()

    def test_remove_artifact_unauthenticated_returns_403(self) -> None:
        """Test that removing an artifact without authentication returns 403."""
        client = Client()

        # Add artifact to release first
        artifact = ReleaseArtifact.objects.create(release=self.release, sbom=self.sbom)

        response = client.delete(
            f"/api/v1/releases/{self.release.id}/artifacts/{artifact.id}",
        )

        assert response.status_code == 403

        # Verify artifact still exists
        assert ReleaseArtifact.objects.filter(id=artifact.id).exists()
