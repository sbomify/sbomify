"""Tests for document refactoring - new forms and views."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from documents.forms import DocumentMetadataForm
from documents.models import Document
from sboms.models import Component
from teams.models import Team, Member

User = get_user_model()


@pytest.fixture
def sample_team():
    """Create a sample team for testing."""
    return Team.objects.create(name="Test Team")


@pytest.fixture
def sample_user(sample_team):
    """Create a sample user for testing."""
    user = User.objects.create_user(username="testuser", email="test@example.com")
    Member.objects.create(user=user, team=sample_team, role="owner", is_default_team=True)
    return user


@pytest.fixture
def sample_document_component(sample_team, sample_user):
    """Create a sample document component for testing."""
    return Component.objects.create(
        name="Test Document Component",
        component_type=Component.ComponentType.DOCUMENT,
        team=sample_team,
    )


@pytest.fixture
def sample_document(sample_document_component):
    """Create a sample document for testing."""
    return Document.objects.create(
        name="Test Document",
        version="1.0",
        document_type=Document.DocumentType.SPECIFICATION,
        description="A test document",
        component=sample_document_component,
        source="manual_upload",
        content_type="application/pdf",
        file_size=1024,
    )


@pytest.mark.django_db
class TestDocumentMetadataForm:
    """Test the DocumentMetadataForm."""

    def test_form_valid_data(self):
        """Test form with valid data."""
        form_data = {
            "name": "Updated Document",
            "version": "2.0",
            "document_type": Document.DocumentType.MANUAL,
            "description": "Updated description",
        }
        form = DocumentMetadataForm(data=form_data)
        assert form.is_valid()

    def test_form_missing_required_name(self):
        """Test form with missing required name."""
        form_data = {
            "version": "2.0",
            "document_type": Document.DocumentType.MANUAL,
            "description": "Updated description",
        }
        form = DocumentMetadataForm(data=form_data)
        assert not form.is_valid()
        assert "name" in form.errors

    def test_form_empty_optional_fields(self):
        """Test form with empty optional fields."""
        form_data = {
            "name": "Updated Document",
            "version": "",
            "document_type": "",
            "description": "",
        }
        form = DocumentMetadataForm(data=form_data)
        if not form.is_valid():
            print("Form errors:", form.errors)  # Debug output
        assert form.is_valid()

    def test_form_with_instance(self, sample_document):
        """Test form with an existing document instance."""
        form = DocumentMetadataForm(instance=sample_document)
        assert form.initial["name"] == sample_document.name
        assert form.initial["version"] == sample_document.version
        assert form.initial["document_type"] == sample_document.document_type
        assert form.initial["description"] == sample_document.description


@pytest.mark.django_db
class TestDocumentMetadataEditView:
    """Test the document metadata edit view."""

    def test_get_metadata_edit_page(self, sample_user, sample_document):
        """Test GET request to metadata edit page."""
        client = Client()
        client.force_login(sample_user)

        url = reverse("documents:document_metadata_edit", args=[sample_document.id])
        response = client.get(url)

        assert response.status_code == 200
        assert "document" in response.context
        assert "form" in response.context
        assert response.context["document"] == sample_document

    def test_post_metadata_edit_success(self, sample_user, sample_document):
        """Test successful POST request to update metadata."""
        client = Client()
        client.force_login(sample_user)

        updated_data = {
            "name": "Updated Document Name",
            "version": "2.0",
            "document_type": Document.DocumentType.MANUAL,
            "description": "Updated description",
        }

        url = reverse("documents:document_metadata_edit", args=[sample_document.id])
        response = client.post(url, data=updated_data)

        # Should redirect after successful update
        assert response.status_code == 302

        # Check that document was updated
        sample_document.refresh_from_db()
        assert sample_document.name == "Updated Document Name"
        assert sample_document.version == "2.0"
        assert sample_document.document_type == Document.DocumentType.MANUAL
        assert sample_document.description == "Updated description"

    def test_metadata_edit_unauthenticated(self, sample_document):
        """Test metadata edit view requires authentication."""
        client = Client()

        url = reverse("documents:document_metadata_edit", args=[sample_document.id])
        response = client.get(url)

        # Should redirect to login
        assert response.status_code == 302
        assert "/login" in response.url

    def test_metadata_edit_forbidden(self, sample_document):
        """Test metadata edit view forbids non-members."""
        # Create a different user not in the team
        other_user = User.objects.create_user(username="other", email="other@example.com")

        client = Client()
        client.force_login(other_user)

        url = reverse("documents:document_metadata_edit", args=[sample_document.id])
        response = client.get(url)

        assert response.status_code == 403

    def test_metadata_edit_document_not_found(self, sample_user):
        """Test metadata edit view with non-existent document."""
        client = Client()
        client.force_login(sample_user)

        url = reverse("documents:document_metadata_edit", args=["nonexistent"])
        response = client.get(url)

        assert response.status_code == 404

    def test_post_metadata_edit_invalid_data(self, sample_user, sample_document):
        """Test POST with invalid data shows form errors."""
        client = Client()
        client.force_login(sample_user)

        # Missing required name
        invalid_data = {
            "name": "",  # Required field
            "version": "2.0",
            "document_type": Document.DocumentType.MANUAL,
            "description": "Updated description",
        }

        url = reverse("documents:document_metadata_edit", args=[sample_document.id])
        response = client.post(url, data=invalid_data)

        # Should stay on the same page with form errors
        assert response.status_code == 200
        assert "form" in response.context
        assert response.context["form"].errors
