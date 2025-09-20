"""Test SBOM tagging endpoints in core.apis."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.shared_fixtures import (
    AuthenticationTestMixin,
    authenticated_api_client,
    get_api_headers,
    guest_api_client,
    team_with_business_plan,
)
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member, Team

User = get_user_model()


@pytest.mark.django_db
class TestSBOMTaggingAPI(AuthenticationTestMixin):
    """Test the SBOM tagging API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, team_with_business_plan, sample_user, guest_user):
        """Set up test data using shared fixtures."""
        self.team1 = team_with_business_plan
        self.user = sample_user
        self.guest_user = guest_user

        # Create second team for cross-team testing
        self.team2 = Team.objects.create(name="Test Team 2")

        # Create products
        self.product1 = Product.objects.create(name="Test Product 1", team=self.team1, is_public=False)
        self.product2 = Product.objects.create(name="Test Product 2", team=self.team2, is_public=True)

        # Create releases
        self.release1 = Release.objects.create(
            name="v1.0.0", product=self.product1, is_latest=False, is_prerelease=False
        )
        self.release2 = Release.objects.create(
            name="v2.0.0", product=self.product1, is_latest=False, is_prerelease=True
        )
        self.latest_release = Release.objects.create(
            name="latest", product=self.product1, is_latest=True, is_prerelease=False
        )

        # Create components
        self.component1 = Component.objects.create(name="Test Component 1", team=self.team1, is_public=False)
        self.component2 = Component.objects.create(name="Test Component 2", team=self.team1, is_public=True)

        # Create SBOMs
        self.sbom1_cdx = SBOM.objects.create(
            name="Test SBOM 1 CDX", component=self.component1, format="cyclonedx", version="1.0"
        )
        self.sbom2_cdx = SBOM.objects.create(
            name="Test SBOM 2 CDX", component=self.component1, format="cyclonedx", version="2.0"
        )
        self.sbom1_spdx = SBOM.objects.create(
            name="Test SBOM 1 SPDX", component=self.component1, format="spdx", version="1.0"
        )

    def test_list_sbom_releases_empty(self, authenticated_api_client):
        """Test listing releases for an SBOM with no releases."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.get(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases", **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert isinstance(data, dict)
        assert "items" in data
        assert "pagination" in data
        assert data["items"] == []

    def test_list_sbom_releases_with_releases(self, authenticated_api_client):
        """Test listing releases for an SBOM that has releases."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add SBOM to release
        ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        response = client.get(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases", **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert isinstance(data, dict)
        assert "items" in data
        assert "pagination" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == str(self.release1.id)
        assert data["items"][0]["name"] == "v1.0.0"
        assert data["items"][0]["product_name"] == "Test Product 1"

    def test_list_sbom_releases_unauthenticated_private(self):
        """Test listing releases for a private SBOM without authentication."""
        client = Client()

        response = client.get(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases")
        assert response.status_code == 403
        data = json.loads(response.content)
        assert "Authentication required" in data["detail"]

    def test_list_sbom_releases_unauthenticated_public(self):
        """Test listing releases for a public SBOM without authentication."""
        client = Client()

        # Make component public
        self.component1.is_public = True
        self.component1.save()

        response = client.get(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases")
        assert response.status_code == 200

    def test_add_sbom_to_releases_new(self, authenticated_api_client):
        """Test adding an SBOM to releases (new case)."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        payload = {"release_ids": [str(self.release1.id), str(self.release2.id)]}

        response = client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201
        data = json.loads(response.content)
        assert len(data["created_artifacts"]) == 2
        assert len(data["replaced_artifacts"]) == 0
        assert len(data["errors"]) == 0

        # Verify artifacts were created
        assert ReleaseArtifact.objects.filter(release=self.release1, sbom=self.sbom1_cdx).exists()
        assert ReleaseArtifact.objects.filter(release=self.release2, sbom=self.sbom1_cdx).exists()

    def test_add_sbom_to_releases_replacement(self, authenticated_api_client):
        """Test adding an SBOM that replaces existing SBOM of same format from same component."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # First, add the original SBOM
        ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        # Now add a different SBOM of the same format from the same component
        payload = {"release_ids": [str(self.release1.id)]}

        response = client.post(
            f"/api/v1/sboms/{self.sbom2_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201
        data = json.loads(response.content)
        assert len(data["created_artifacts"]) == 0
        assert len(data["replaced_artifacts"]) == 1
        assert len(data["errors"]) == 0
        assert data["replaced_artifacts"][0]["replaced_sbom"] == "Test SBOM 1 CDX"

        # Verify the old SBOM was replaced
        assert not ReleaseArtifact.objects.filter(release=self.release1, sbom=self.sbom1_cdx).exists()
        assert ReleaseArtifact.objects.filter(release=self.release1, sbom=self.sbom2_cdx).exists()

    def test_add_sbom_different_format_no_replacement(self, authenticated_api_client):
        """Test adding an SBOM of different format doesn't replace existing SBOM."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # First, add CDX SBOM
        ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        # Now add SPDX SBOM (different format)
        payload = {"release_ids": [str(self.release1.id)]}

        response = client.post(
            f"/api/v1/sboms/{self.sbom1_spdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201
        data = json.loads(response.content)
        assert len(data["created_artifacts"]) == 1
        assert len(data["replaced_artifacts"]) == 0
        assert len(data["errors"]) == 0

        # Verify both SBOMs exist in the release
        assert ReleaseArtifact.objects.filter(release=self.release1, sbom=self.sbom1_cdx).exists()
        assert ReleaseArtifact.objects.filter(release=self.release1, sbom=self.sbom1_spdx).exists()

    def test_add_sbom_to_latest_release_forbidden(self, authenticated_api_client):
        """Test that adding SBOM to 'latest' release is forbidden."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        payload = {"release_ids": [str(self.latest_release.id)]}

        response = client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_sbom_already_exists(self, authenticated_api_client):
        """Test adding the same SBOM to a release where it already exists."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # First, add the SBOM
        ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        # Try to add the same SBOM again
        payload = {"release_ids": [str(self.release1.id)]}

        response = client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_sbom_different_team(self, authenticated_api_client):
        """Test adding SBOM to release from different team."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        payload = {"release_ids": [str(self.product2.releases.create(name="v1.0.0", is_latest=False).id)]}

        response = client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_sbom_invalid_payload(self, authenticated_api_client):
        """Test adding SBOM with invalid payload."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Missing release_ids
        response = client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps({}),
            content_type="application/json",
            **headers,
        )
        assert response.status_code == 422  # Schema validation error

        # Empty release_ids
        response = client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps({"release_ids": []}),
            content_type="application/json",
            **headers,
        )
        assert response.status_code == 422  # Schema validation error

    def test_add_sbom_unauthorized(self, guest_api_client):
        """Test adding SBOM without proper permissions."""
        client, access_token = guest_api_client
        headers = get_api_headers(access_token)

        # Add guest user to team as guest
        Member.objects.create(user=self.guest_user, team=self.team1, role="guest")

        payload = {"release_ids": [str(self.release1.id)]}

        response = client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 403
        data = json.loads(response.content)
        assert "Only owners and admins" in data["detail"]

    def test_remove_sbom_from_release(self, authenticated_api_client):
        """Test removing an SBOM from a release."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # First, add the SBOM
        artifact = ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        response = client.delete(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{self.release1.id}", **headers
        )

        assert response.status_code == 204
        assert not ReleaseArtifact.objects.filter(id=artifact.id).exists()

    def test_remove_sbom_not_in_release(self, authenticated_api_client):
        """Test removing an SBOM that's not in the release."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.delete(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{self.release1.id}", **headers
        )

        assert response.status_code == 404
        data = json.loads(response.content)
        assert "not in this release" in data["detail"]

    def test_remove_sbom_from_latest_release_forbidden(self, authenticated_api_client):
        """Test that removing SBOM from 'latest' release is forbidden."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add SBOM to latest release (this would normally be done automatically)
        ReleaseArtifact.objects.create(release=self.latest_release, sbom=self.sbom1_cdx)

        response = client.delete(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{self.latest_release.id}", **headers
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "automatically managed" in data["detail"]

    def test_remove_sbom_different_team(self, authenticated_api_client):
        """Test removing SBOM from release belonging to different team."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Create release in different team
        other_release = Release.objects.create(name="v1.0.0", product=self.product2, is_latest=False)

        response = client.delete(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{other_release.id}", **headers
        )

        assert response.status_code == 403
        data = json.loads(response.content)
        assert "Access denied" in data["detail"]

    def test_sbom_not_found(self, authenticated_api_client):
        """Test endpoints with non-existent SBOM."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        fake_id = "00000000-0000-0000-0000-000000000000"

        # List releases
        response = client.get(f"/api/v1/sboms/{fake_id}/releases", **headers)
        assert response.status_code == 404

        # Add to releases
        response = client.post(
            f"/api/v1/sboms/{fake_id}/releases",
            data=json.dumps({"release_ids": [str(self.release1.id)]}),
            content_type="application/json",
            **headers,
        )
        assert response.status_code == 404

        # Remove from release
        response = client.delete(f"/api/v1/sboms/{fake_id}/releases/{self.release1.id}", **headers)
        assert response.status_code == 404

    def test_release_not_found(self, authenticated_api_client):
        """Test endpoints with non-existent release."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        fake_id = "00000000-0000-0000-0000-000000000000"

        # Add to releases
        response = client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps({"release_ids": [fake_id]}),
            content_type="application/json",
            **headers,
        )
        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

        # Remove from release
        response = client.delete(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{fake_id}", **headers)
        assert response.status_code == 404
