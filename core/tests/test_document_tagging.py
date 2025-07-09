"""Test document tagging endpoints in core.apis."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from access_tokens.models import AccessToken
from access_tokens.utils import create_personal_access_token
from core.models import Component, Product, Release, ReleaseArtifact
from documents.models import Document
from teams.models import Member, Team

User = get_user_model()


@pytest.mark.django_db
class TestDocumentTaggingAPI:
    """Test the document tagging API endpoints."""

    def setup_method(self):
        """Set up test data."""
        # Create teams
        self.team1 = Team.objects.create(name="Test Team 1")
        self.team2 = Team.objects.create(name="Test Team 2")

        # Create products
        self.product1 = Product.objects.create(name="Test Product 1", team=self.team1)
        self.product2 = Product.objects.create(name="Test Product 2", team=self.team2)

        # Create releases
        self.release1 = Release.objects.create(name="v1.0", product=self.product1, description="Release 1")
        self.release2 = Release.objects.create(name="v2.0", product=self.product1, description="Release 2")
        self.latest_release = Release.objects.create(
            name="latest", product=self.product1, is_latest=True, description="Latest release"
        )
        self.other_team_release = Release.objects.create(
            name="v1.0", product=self.product2, description="Other team release"
        )

        # Create components
        self.component1 = Component.objects.create(
            name="Test Component 1", team=self.team1, component_type=Component.ComponentType.DOCUMENT
        )
        self.component2 = Component.objects.create(
            name="Test Component 2", team=self.team2, component_type=Component.ComponentType.DOCUMENT
        )

        # Create documents
        self.doc1_spec = Document.objects.create(
            name="Test Doc 1 Spec", component=self.component1, document_type="specification", version="1.0"
        )
        self.doc2_spec = Document.objects.create(
            name="Test Doc 2 Spec", component=self.component1, document_type="specification", version="2.0"
        )
        self.doc1_manual = Document.objects.create(
            name="Test Doc 1 Manual", component=self.component1, document_type="manual", version="1.0"
        )

        # Set up authenticated client
        self.client = Client()

        # Create test user and access token
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass")
        token_str = create_personal_access_token(self.user)
        self.access_token = AccessToken.objects.create(
            user=self.user, encoded_token=token_str, description="Test Token"
        )

        # Add user to team1 as admin
        Member.objects.create(user=self.user, team=self.team1, role="admin")

    def _get_headers(self):
        """Get authentication headers."""
        return {"HTTP_AUTHORIZATION": f"Bearer {self.access_token.encoded_token}"}

    def test_list_document_releases_empty(self):
        """Test listing releases for a document with no releases."""
        response = self.client.get(f"/api/v1/documents/{self.doc1_spec.id}/releases", **self._get_headers())
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data == []

    def test_list_document_releases_with_data(self):
        """Test listing releases for a document that is in releases."""
        # Add document to releases
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)
        ReleaseArtifact.objects.create(release=self.release2, document=self.doc1_spec)

        response = self.client.get(f"/api/v1/documents/{self.doc1_spec.id}/releases", **self._get_headers())
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data) == 2

        # Check release data structure
        release_names = [r["name"] for r in data]
        assert "v1.0" in release_names
        assert "v2.0" in release_names

    def test_add_document_to_releases_new(self):
        """Test adding document to new releases."""
        payload = {"release_ids": [str(self.release1.id), str(self.release2.id)]}

        response = self.client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
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
        assert ReleaseArtifact.objects.filter(release=self.release1, document=self.doc1_spec).exists()
        assert ReleaseArtifact.objects.filter(release=self.release2, document=self.doc1_spec).exists()

    def test_add_document_to_releases_with_replacement(self):
        """Test adding document to release that already has same document type from same component."""
        # Add first document to release
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        # Now add second document of same type to same release
        payload = {"release_ids": [str(self.release1.id)]}

        response = self.client.post(
            f"/api/v1/documents/{self.doc2_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 201
        data = json.loads(response.content)
        assert len(data["created_artifacts"]) == 0
        assert len(data["replaced_artifacts"]) == 1
        assert len(data["errors"]) == 0

        # Verify the replacement
        replaced = data["replaced_artifacts"][0]
        assert replaced["replaced_document"] == "Test Doc 1 Spec"

        # Verify only the new document is in the release
        artifacts = ReleaseArtifact.objects.filter(release=self.release1, document__document_type="specification")
        assert artifacts.count() == 1
        assert artifacts.first().document == self.doc2_spec

    def test_add_document_to_releases_different_types_no_replacement(self):
        """Test adding documents of different types doesn't trigger replacement."""
        # Add specification document to release
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        # Add manual document to same release - should not replace
        payload = {"release_ids": [str(self.release1.id)]}

        response = self.client.post(
            f"/api/v1/documents/{self.doc1_manual.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 201
        data = json.loads(response.content)
        assert len(data["created_artifacts"]) == 1
        assert len(data["replaced_artifacts"]) == 0
        assert len(data["errors"]) == 0

        # Verify both documents are in the release
        assert ReleaseArtifact.objects.filter(release=self.release1, document=self.doc1_spec).exists()
        assert ReleaseArtifact.objects.filter(release=self.release1, document=self.doc1_manual).exists()

    def test_add_document_to_latest_release_forbidden(self):
        """Test that adding document to 'latest' release is forbidden."""
        payload = {"release_ids": [str(self.latest_release.id)]}

        response = self.client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_document_to_releases_already_exists(self):
        """Test adding same document to release it's already in."""
        # Add document to release first
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        payload = {"release_ids": [str(self.release1.id)]}

        response = self.client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_document_to_releases_different_team(self):
        """Test adding document to release from different team."""
        payload = {"release_ids": [str(self.other_team_release.id)]}

        response = self.client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_document_to_releases_nonexistent_release(self):
        """Test adding document to non-existent release."""
        payload = {"release_ids": ["nonexistent-id"]}

        response = self.client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_document_to_releases_invalid_payload(self):
        """Test adding document with invalid payload."""
        # Missing release_ids
        response = self.client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps({}),
            content_type="application/json",
            **self._get_headers(),
        )
        assert response.status_code == 422  # Schema validation error

        # Empty release_ids
        response = self.client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps({"release_ids": []}),
            content_type="application/json",
            **self._get_headers(),
        )
        assert response.status_code == 422  # Schema validation error

    def test_add_document_to_releases_no_permission(self):
        """Test adding document without proper permissions."""
        # Create token with guest role
        guest_user = User.objects.create_user(username="guestuser", email="guest@example.com", password="guestpass")
        guest_token_str = create_personal_access_token(guest_user)
        guest_token = AccessToken.objects.create(
            user=guest_user, encoded_token=guest_token_str, description="Guest Token"
        )

        # Add guest user to team with guest role
        Member.objects.create(user=guest_user, team=self.team1, role="guest")

        payload = {"release_ids": [str(self.release1.id)]}

        response = self.client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {guest_token.encoded_token}",
        )

        assert response.status_code == 403

    def test_remove_document_from_release(self):
        """Test removing document from release."""
        # Add document to release first
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        response = self.client.delete(
            f"/api/v1/documents/{self.doc1_spec.id}/releases/{self.release1.id}", **self._get_headers()
        )

        assert response.status_code == 204
        assert not ReleaseArtifact.objects.filter(release=self.release1, document=self.doc1_spec).exists()

    def test_remove_document_from_release_not_in_release(self):
        """Test removing document from release when it's not in the release."""
        response = self.client.delete(
            f"/api/v1/documents/{self.doc1_spec.id}/releases/{self.release1.id}", **self._get_headers()
        )

        assert response.status_code == 404

    def test_remove_document_from_latest_release_forbidden(self):
        """Test that removing document from 'latest' release is forbidden."""
        # Add document to latest release first
        ReleaseArtifact.objects.create(release=self.latest_release, document=self.doc1_spec)

        response = self.client.delete(
            f"/api/v1/documents/{self.doc1_spec.id}/releases/{self.latest_release.id}", **self._get_headers()
        )

        assert response.status_code == 400

    def test_document_not_found(self):
        """Test endpoints with non-existent document."""
        # Test list releases
        response = self.client.get("/api/v1/documents/nonexistent/releases", **self._get_headers())
        assert response.status_code == 404

        # Test add to releases
        payload = {"release_ids": [str(self.release1.id)]}
        response = self.client.post(
            "/api/v1/documents/nonexistent/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **self._get_headers(),
        )
        assert response.status_code == 404

        # Test remove from release
        response = self.client.delete(
            f"/api/v1/documents/nonexistent/releases/{self.release1.id}", **self._get_headers()
        )
        assert response.status_code == 404

    def test_unauthenticated_access_public_document(self):
        """Test unauthenticated access to public document releases."""
        # Make component public
        self.component1.is_public = True
        self.component1.save()

        # Make product public
        self.product1.is_public = True
        self.product1.save()

        # Add document to release
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        response = self.client.get(f"/api/v1/documents/{self.doc1_spec.id}/releases")
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data) == 1

    def test_unauthenticated_access_private_document(self):
        """Test unauthenticated access to private document releases."""
        response = self.client.get(f"/api/v1/documents/{self.doc1_spec.id}/releases")
        assert response.status_code == 403
