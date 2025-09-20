import pytest
from django.test import TestCase
from django.contrib.auth.models import User
from django.test import RequestFactory

from sbomify.apps.teams.models import Team
from sbomify.apps.core.models import Product, Release, ReleaseArtifact
from sbomify.apps.sboms.models import Component, SBOM
from sbomify.apps.core.apis import list_release_artifacts


class TestReleaseArtifactsAPI(TestCase):
    """Test release artifacts API to ensure correct version field mapping."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()

        # Create test team
        self.team = Team.objects.create(
            key="test-team",
            name="Test Team"
        )

        # Create test product
        self.product = Product.objects.create(
            team=self.team,
            name="Test Product",
            is_public=True
        )

        # Create test release
        self.release = Release.objects.create(
            product=self.product,
            name="v1.0.0",
            description="Test release"
        )

        # Create test component
        self.component = Component.objects.create(
            team=self.team,
            name="test-component",
            component_type=Component.ComponentType.SBOM,
            is_public=True
        )

        # Create test SBOM with different version and format_version
        self.sbom = SBOM.objects.create(
            name="test-sbom",
            version="sha256:abc123def456",  # Actual SBOM version
            format="cyclonedx",
            format_version="1.5",  # CDX format version
            component=self.component,
            source="test"
        )

        # Add SBOM to release as artifact
        self.release_artifact = ReleaseArtifact.objects.create(
            release=self.release,
            sbom=self.sbom
        )

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
        request = self.factory.get(f'/api/v1/releases/{self.release.id}/artifacts?mode=existing&page=1&page_size=15')
        request.user = None

        # Call the API function directly
        response_data = list_release_artifacts(request, str(self.release.id), mode='existing')

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
        request = self.factory.get(f'/api/v1/releases/{self.release.id}/artifacts?mode=existing&page=1&page_size=15')
        request.user = None

        response_data = list_release_artifacts(request, str(self.release.id), mode='existing')

        # Should return a dict with items and pagination
        self.assertIsInstance(response_data, dict)
        self.assertIn("items", response_data)

        # Find the empty version artifact
        empty_artifact = None
        for artifact in response_data["items"]:
            if artifact['artifact_name'] == 'test-sbom-empty':
                empty_artifact = artifact
                break

        self.assertIsNotNone(empty_artifact)
        self.assertEqual(empty_artifact["sbom_version"], "")  # Should be empty string for None version