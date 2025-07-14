import pytest
from django.test import TestCase
from django.contrib.auth.models import User
from django.test import RequestFactory

from teams.models import Team
from core.models import Product, Release, ReleaseArtifact
from sboms.models import Component, SBOM
from core.apis import list_release_artifacts


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
        """Test that sbom_version field returns the actual SBOM version, not format version.

        This test catches the critical bug where sbom_version was incorrectly
        returning the format version instead of the actual SBOM version.
        """
        # Make API request
        request = self.factory.get(f'/api/v1/releases/{self.release.id}/artifacts?mode=existing')
        request.user = None

        # Call the API function directly
        response_data = list_release_artifacts(request, str(self.release.id), mode='existing')

        # Should return a list of artifacts
        self.assertIsInstance(response_data, list)
        self.assertEqual(len(response_data), 1)

        artifact = response_data[0]
        self.assertEqual(artifact['artifact_type'], 'sbom')

        # CRITICAL: sbom_version should return the actual SBOM version
        # NOT the format version
        self.assertEqual(
            artifact['sbom_version'],
            "sha256:abc123def456",  # Actual SBOM version
            "sbom_version should return the actual SBOM version, not format version"
        )

        # sbom_format_version should return the format version
        self.assertEqual(
            artifact.get('sbom_format_version'),
            "1.5",  # Format version
            "sbom_format_version should return the format version"
        )

        # Additional checks
        self.assertEqual(artifact['sbom_format'], 'cyclonedx')
        self.assertEqual(artifact['artifact_name'], 'test-sbom')

    def test_empty_sbom_version_returns_empty_string(self):
        """Test that empty SBOM version returns empty string, not format version."""
        # Create SBOM with empty version
        sbom_empty = SBOM.objects.create(
            name="test-sbom-empty",
            version="",  # Empty version
            format="spdx",
            format_version="2.3",  # Format version
            component=self.component,
            source="test"
        )

        # Add to release
        ReleaseArtifact.objects.create(
            release=self.release,
            sbom=sbom_empty
        )

        # Make API request
        request = self.factory.get(f'/api/v1/releases/{self.release.id}/artifacts?mode=existing')
        request.user = None

        response_data = list_release_artifacts(request, str(self.release.id), mode='existing')

        # Find the empty version artifact
        empty_artifact = None
        for artifact in response_data:
            if artifact['artifact_name'] == 'test-sbom-empty':
                empty_artifact = artifact
                break

        self.assertIsNotNone(empty_artifact)

        # Even with empty version, should NOT return format version
        self.assertEqual(
            empty_artifact['sbom_version'],
            "",  # Should be empty string
            "Empty sbom_version should return empty string, not format version"
        )

        self.assertEqual(
            empty_artifact.get('sbom_format_version'),
            "2.3",  # Format version should be separate
            "sbom_format_version should return the format version"
        )