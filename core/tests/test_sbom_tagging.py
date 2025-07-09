"""Test SBOM tagging endpoints in core.apis."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from access_tokens.models import AccessToken
from access_tokens.utils import create_personal_access_token
from core.models import Component, Product, Release, ReleaseArtifact
from sboms.models import SBOM
from teams.models import Member, Team

User = get_user_model()


@pytest.mark.django_db
class TestSBOMTaggingAPI:
    """Test the SBOM tagging API endpoints."""

    def setup_method(self):
        """Set up test data."""
        # Create teams
        self.team1 = Team.objects.create(name="Test Team 1")
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

        # Set up authenticated client
        self.client = Client()

        # Create test user and access token
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass")
        token_str = create_personal_access_token(self.user)
        self.access_token = AccessToken.objects.create(
            user=self.user, encoded_token=token_str, description="Test Token"
        )

        # Add user to team as admin
        self.member = Member.objects.create(user=self.user, team=self.team1, role="admin", is_default_team=True)

    def _get_headers(self):
        """Get authentication headers."""
        return {"HTTP_AUTHORIZATION": f"Bearer {self.access_token.encoded_token}"}

    def test_list_sbom_releases_empty(self):
        """Test listing releases for an SBOM with no releases."""
        response = self.client.get(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases", **self._get_headers())
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data == []

    def test_list_sbom_releases_with_releases(self):
        """Test listing releases for an SBOM that has releases."""
        # Add SBOM to release
        ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        response = self.client.get(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases", **self._get_headers())
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data) == 1
        assert data[0]["id"] == str(self.release1.id)
        assert data[0]["name"] == "v1.0.0"
        assert data[0]["product_name"] == "Test Product 1"

    def test_list_sbom_releases_unauthenticated_private(self):
        """Test listing releases for a private SBOM without authentication."""
        response = self.client.get(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases")
        assert response.status_code == 403
        data = json.loads(response.content)
        assert "Authentication required" in data["detail"]

    def test_list_sbom_releases_unauthenticated_public(self):
        """Test listing releases for a public SBOM without authentication."""
        # Make component public
        self.component1.is_public = True
        self.component1.save()

        response = self.client.get(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases")
        assert response.status_code == 200

    def test_add_sbom_to_releases_new(self):
        """Test adding an SBOM to releases (new case)."""
        payload = {"release_ids": [str(self.release1.id), str(self.release2.id)]}

        response = self.client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 201
        data = json.loads(response.content)
        assert len(data["created_artifacts"]) == 2
        assert len(data["replaced_artifacts"]) == 0
        assert len(data["errors"]) == 0

        # Verify artifacts were created
        assert ReleaseArtifact.objects.filter(release=self.release1, sbom=self.sbom1_cdx).exists()
        assert ReleaseArtifact.objects.filter(release=self.release2, sbom=self.sbom1_cdx).exists()

    def test_add_sbom_to_releases_replacement(self):
        """Test adding an SBOM that replaces existing SBOM of same format from same component."""
        # First, add the original SBOM
        ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        # Now add a different SBOM of the same format from the same component
        payload = {"release_ids": [str(self.release1.id)]}

        response = self.client.post(
            f"/api/v1/sboms/{self.sbom2_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
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

    def test_add_sbom_different_format_no_replacement(self):
        """Test adding an SBOM of different format doesn't replace existing SBOM."""
        # First, add CDX SBOM
        ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        # Now add SPDX SBOM (different format)
        payload = {"release_ids": [str(self.release1.id)]}

        response = self.client.post(
            f"/api/v1/sboms/{self.sbom1_spdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 201
        data = json.loads(response.content)
        assert len(data["created_artifacts"]) == 1
        assert len(data["replaced_artifacts"]) == 0
        assert len(data["errors"]) == 0

        # Verify both SBOMs exist in the release
        assert ReleaseArtifact.objects.filter(release=self.release1, sbom=self.sbom1_cdx).exists()
        assert ReleaseArtifact.objects.filter(release=self.release1, sbom=self.sbom1_spdx).exists()

    def test_add_sbom_to_latest_release_forbidden(self):
        """Test that adding SBOM to 'latest' release is forbidden."""
        payload = {"release_ids": [str(self.latest_release.id)]}

        response = self.client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_sbom_already_exists(self):
        """Test adding the same SBOM to a release where it already exists."""
        # First, add the SBOM
        ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        # Try to add the same SBOM again
        payload = {"release_ids": [str(self.release1.id)]}

        response = self.client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_sbom_different_team(self):
        """Test adding SBOM to release from different team."""
        payload = {"release_ids": [str(self.product2.releases.create(name="v1.0.0", is_latest=False).id)]}

        response = self.client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_sbom_invalid_payload(self):
        """Test adding SBOM with invalid payload."""
        # Missing release_ids
        response = self.client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps({}),
            content_type="application/json",
            **self._get_headers(),
        )
        assert response.status_code == 422  # Schema validation error

        # Empty release_ids
        response = self.client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps({"release_ids": []}),
            content_type="application/json",
            **self._get_headers(),
        )
        assert response.status_code == 422  # Schema validation error

    def test_add_sbom_unauthorized(self):
        """Test adding SBOM without proper permissions."""
        # Create token with guest role
        guest_user = User.objects.create_user(username="guestuser", email="guest@example.com", password="guestpass")
        guest_token_str = create_personal_access_token(guest_user)
        guest_token = AccessToken.objects.create(
            user=guest_user, encoded_token=guest_token_str, description="Guest Token"
        )
        # Add guest user to team as guest
        Member.objects.create(user=guest_user, team=self.team1, role="guest")

        payload = {"release_ids": [str(self.release1.id)]}

        response = self.client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {guest_token.encoded_token}",
        )

        assert response.status_code == 403
        data = json.loads(response.content)
        assert "Only owners and admins" in data["detail"]

    def test_remove_sbom_from_release(self):
        """Test removing an SBOM from a release."""
        # First, add the SBOM
        artifact = ReleaseArtifact.objects.create(release=self.release1, sbom=self.sbom1_cdx)

        response = self.client.delete(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{self.release1.id}", **self._get_headers()
        )

        assert response.status_code == 204
        assert not ReleaseArtifact.objects.filter(id=artifact.id).exists()

    def test_remove_sbom_not_in_release(self):
        """Test removing an SBOM that's not in the release."""
        response = self.client.delete(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{self.release1.id}", **self._get_headers()
        )

        assert response.status_code == 404
        data = json.loads(response.content)
        assert "not in this release" in data["detail"]

    def test_remove_sbom_from_latest_release_forbidden(self):
        """Test that removing SBOM from 'latest' release is forbidden."""
        # Add SBOM to latest release (this would normally be done automatically)
        ReleaseArtifact.objects.create(release=self.latest_release, sbom=self.sbom1_cdx)

        response = self.client.delete(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{self.latest_release.id}", **self._get_headers()
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "automatically managed" in data["detail"]

    def test_remove_sbom_different_team(self):
        """Test removing SBOM from release belonging to different team."""
        # Create release in different team
        other_release = Release.objects.create(name="v1.0.0", product=self.product2, is_latest=False)

        response = self.client.delete(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{other_release.id}", **self._get_headers()
        )

        assert response.status_code == 403
        data = json.loads(response.content)
        assert "different team" in data["detail"]

    def test_sbom_not_found(self):
        """Test endpoints with non-existent SBOM."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        # List releases
        response = self.client.get(f"/api/v1/sboms/{fake_id}/releases", **self._get_headers())
        assert response.status_code == 404

        # Add to releases
        response = self.client.post(
            f"/api/v1/sboms/{fake_id}/releases",
            data=json.dumps({"release_ids": [str(self.release1.id)]}),
            content_type="application/json",
            **self._get_headers(),
        )
        assert response.status_code == 404

        # Remove from release
        response = self.client.delete(f"/api/v1/sboms/{fake_id}/releases/{self.release1.id}", **self._get_headers())
        assert response.status_code == 404

    def test_release_not_found(self):
        """Test endpoints with non-existent release."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        # Add to releases
        response = self.client.post(
            f"/api/v1/sboms/{self.sbom1_cdx.id}/releases",
            data=json.dumps({"release_ids": [fake_id]}),
            content_type="application/json",
            **self._get_headers(),
        )
        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

        # Remove from release
        response = self.client.delete(f"/api/v1/sboms/{self.sbom1_cdx.id}/releases/{fake_id}", **self._get_headers())
        assert response.status_code == 404
