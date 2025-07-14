"""Test document tagging endpoints in core.apis."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from core.models import Component, Product, Release, ReleaseArtifact
from core.tests.shared_fixtures import (
    AuthenticationTestMixin,
    authenticated_api_client,
    get_api_headers,
    guest_api_client,
    team_with_business_plan,
)
from documents.models import Document
from teams.models import Team

User = get_user_model()


@pytest.mark.django_db
class TestDocumentTaggingAPI(AuthenticationTestMixin):
    """Test the document tagging API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, team_with_business_plan, sample_user, guest_user):
        """Set up test data using shared fixtures."""
        self.team1 = team_with_business_plan
        self.user = sample_user
        self.guest_user = guest_user

        # Create second team for cross-team testing
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

    def test_list_document_releases_empty(self, authenticated_api_client):
        """Test listing releases for a document with no releases."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.get(f"/api/v1/documents/{self.doc1_spec.id}/releases", **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert isinstance(data, dict)
        assert "items" in data
        assert "pagination" in data
        assert data["items"] == []

    def test_list_document_releases_with_data(self, authenticated_api_client):
        """Test listing releases for a document that is in releases."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add document to releases
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)
        ReleaseArtifact.objects.create(release=self.release2, document=self.doc1_spec)

        response = client.get(f"/api/v1/documents/{self.doc1_spec.id}/releases", **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert isinstance(data, dict)
        assert "items" in data
        assert "pagination" in data
        assert len(data["items"]) == 2

        # Check release data structure
        release_names = [r["name"] for r in data["items"]]
        assert "v1.0" in release_names
        assert "v2.0" in release_names

    def test_add_document_to_releases_new(self, authenticated_api_client):
        """Test adding document to new releases."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        payload = {"release_ids": [str(self.release1.id), str(self.release2.id)]}

        response = client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
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
        assert ReleaseArtifact.objects.filter(release=self.release1, document=self.doc1_spec).exists()
        assert ReleaseArtifact.objects.filter(release=self.release2, document=self.doc1_spec).exists()

    def test_add_document_to_releases_with_replacement(self, authenticated_api_client):
        """Test adding document to release that already has same document type from same component."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add first document to release
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        # Now add second document of same type to same release
        payload = {"release_ids": [str(self.release1.id)]}

        response = client.post(
            f"/api/v1/documents/{self.doc2_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
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

    def test_add_document_to_releases_different_types_no_replacement(self, authenticated_api_client):
        """Test adding documents of different types doesn't trigger replacement."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add specification document to release
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        # Add manual document to same release - should not replace
        payload = {"release_ids": [str(self.release1.id)]}

        response = client.post(
            f"/api/v1/documents/{self.doc1_manual.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 201
        data = json.loads(response.content)
        assert len(data["created_artifacts"]) == 1
        assert len(data["replaced_artifacts"]) == 0
        assert len(data["errors"]) == 0

        # Verify both documents are in the release
        assert ReleaseArtifact.objects.filter(release=self.release1, document=self.doc1_spec).exists()
        assert ReleaseArtifact.objects.filter(release=self.release1, document=self.doc1_manual).exists()

    def test_add_document_to_latest_release_forbidden(self, authenticated_api_client):
        """Test that adding document to 'latest' release is forbidden."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        payload = {"release_ids": [str(self.latest_release.id)]}

        response = client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_document_to_releases_already_exists(self, authenticated_api_client):
        """Test adding same document to release it's already in."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add document to release first
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        payload = {"release_ids": [str(self.release1.id)]}

        response = client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_document_to_releases_different_team(self, authenticated_api_client):
        """Test adding document to release from different team."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        payload = {"release_ids": [str(self.other_team_release.id)]}

        response = client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_document_to_releases_nonexistent_release(self, authenticated_api_client):
        """Test adding document to non-existent release."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        payload = {"release_ids": ["nonexistent-id"]}

        response = client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "No artifacts were created or replaced" in data["detail"]

    def test_add_document_to_releases_invalid_payload(self, authenticated_api_client):
        """Test adding document with invalid payload."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Missing release_ids
        response = client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps({}),
            content_type="application/json",
            **headers,
        )
        assert response.status_code == 422  # Schema validation error

        # Empty release_ids
        response = client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps({"release_ids": []}),
            content_type="application/json",
            **headers,
        )
        assert response.status_code == 422  # Schema validation error

    def test_add_document_to_releases_no_permission(self, guest_api_client):
        """Test adding document without proper permissions."""
        client, access_token = guest_api_client
        headers = get_api_headers(access_token)

        # Add guest user to team with guest role
        from teams.models import Member
        Member.objects.create(user=self.guest_user, team=self.team1, role="guest")

        payload = {"release_ids": [str(self.release1.id)]}

        response = client.post(
            f"/api/v1/documents/{self.doc1_spec.id}/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

        assert response.status_code == 403

    def test_remove_document_from_release(self, authenticated_api_client):
        """Test removing document from release."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add document to release first
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        response = client.delete(
            f"/api/v1/documents/{self.doc1_spec.id}/releases/{self.release1.id}", **headers
        )

        assert response.status_code == 204
        assert not ReleaseArtifact.objects.filter(release=self.release1, document=self.doc1_spec).exists()

    def test_remove_document_from_release_not_in_release(self, authenticated_api_client):
        """Test removing document from release when it's not in the release."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        response = client.delete(
            f"/api/v1/documents/{self.doc1_spec.id}/releases/{self.release1.id}", **headers
        )

        assert response.status_code == 404

    def test_remove_document_from_latest_release_forbidden(self, authenticated_api_client):
        """Test that removing document from 'latest' release is forbidden."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Add document to latest release first
        ReleaseArtifact.objects.create(release=self.latest_release, document=self.doc1_spec)

        response = client.delete(
            f"/api/v1/documents/{self.doc1_spec.id}/releases/{self.latest_release.id}", **headers
        )

        assert response.status_code == 400

    def test_document_not_found(self, authenticated_api_client):
        """Test endpoints with non-existent document."""
        client, access_token = authenticated_api_client
        headers = get_api_headers(access_token)

        # Test list releases
        response = client.get("/api/v1/documents/nonexistent/releases", **headers)
        assert response.status_code == 404

        # Test add to releases
        payload = {"release_ids": [str(self.release1.id)]}
        response = client.post(
            "/api/v1/documents/nonexistent/releases",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )
        assert response.status_code == 404

        # Test remove from release
        response = client.delete(
            f"/api/v1/documents/nonexistent/releases/{self.release1.id}", **headers
        )
        assert response.status_code == 404

    def test_unauthenticated_access_public_document(self):
        """Test unauthenticated access to public document releases."""
        client = Client()

        # Make component public
        self.component1.is_public = True
        self.component1.save()

        # Make product public
        self.product1.is_public = True
        self.product1.save()

        # Add document to release
        ReleaseArtifact.objects.create(release=self.release1, document=self.doc1_spec)

        response = client.get(f"/api/v1/documents/{self.doc1_spec.id}/releases")
        assert response.status_code == 200
        data = json.loads(response.content)
        assert isinstance(data, dict)
        assert "items" in data
        assert "pagination" in data
        assert len(data["items"]) == 1

    def test_unauthenticated_access_private_document(self):
        """Test unauthenticated access to private document releases."""
        client = Client()

        response = client.get(f"/api/v1/documents/{self.doc1_spec.id}/releases")
        assert response.status_code == 403
