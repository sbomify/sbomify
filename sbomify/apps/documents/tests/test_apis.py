"""Tests for documents API endpoints."""

import json

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.shared_fixtures import authenticated_api_client, get_api_headers, guest_user, sample_user
from sbomify.apps.core.tests.s3_fixtures import create_documents_api_mock
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.fixtures import sample_team  # noqa: F401
from sbomify.apps.teams.models import Member 

from ..models import Document


@pytest.fixture
def sample_document_component(sample_team, sample_user):  # noqa: F811
    """Create a sample document component for testing."""
    # Add sample_user as owner to the team for proper permissions
    Member.objects.get_or_create(user=sample_user, team=sample_team, defaults={"role": "owner"})

    return Component.objects.create(
        name="Test Document Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
        visibility=Component.Visibility.PRIVATE,
    )


@pytest.fixture
def sample_document(sample_document_component):
    """Create a sample document for testing."""
    return Document.objects.create(
        name="Test Document",
        version="1.0",
        document_filename="test_file.pdf",
        component=sample_document_component,
        source="manual_upload",
        content_type="application/pdf",
        file_size=1024,
    )


@pytest.mark.django_db
def test_create_document_unauthenticated(client: Client, sample_document_component):
    """Test that unauthenticated users cannot upload documents."""
    test_file = SimpleUploadedFile("test_document.pdf", b"test document content", content_type="application/pdf")

    response = client.post(
        reverse("api-1:create_document"),
        {"document_file": test_file, "component_id": sample_document_component.id, "version": "1.0"},
        format="multipart",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_create_document_file_upload_success(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document_component,
):
    """Test successful document upload via file upload."""
    create_documents_api_mock(mocker, scenario="success")

    client.force_login(sample_user)

    test_file = SimpleUploadedFile("test_document.pdf", b"test document content", content_type="application/pdf")

    response = client.post(
        reverse("api-1:create_document"),
        {
            "document_file": test_file,
            "component_id": sample_document_component.id,
            "version": "1.0",
            "document_type": "specification",
            "description": "Test document description",
        },
        format="multipart",
    )

    assert response.status_code == 201
    data = json.loads(response.content)
    assert "id" in data

    # Verify document was created
    document = Document.objects.get(id=data["id"])
    assert document.name == "test_document"
    assert document.version == "1.0"
    assert document.document_type == "specification"
    assert document.description == "Test document description"
    assert document.source == "manual_upload"
    assert document.content_type == "application/pdf"
    assert document.component == sample_document_component


@pytest.mark.django_db
def test_create_document_raw_data_success(
    mocker: MockerFixture,
    authenticated_api_client,
    sample_document_component,
):
    """Test successful document upload via raw data (API)."""
    create_documents_api_mock(mocker, scenario="success")

    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    url = reverse("api-1:create_document") + (
        f"?component_id={sample_document_component.id}&name=API Document&version=2.0"
        f"&document_type=manual&description=API uploaded document"
    )
    response = client.post(
        url,
        b"document content",  # Raw body content
        content_type="application/octet-stream",
        **headers,
    )

    assert response.status_code == 201
    data = json.loads(response.content)
    assert "id" in data

    # Verify document was created
    document = Document.objects.get(id=data["id"])
    assert document.name == "API Document"
    assert document.version == "2.0"
    assert document.document_type == "manual"
    assert document.description == "API uploaded document"
    assert document.source == "api"
    assert document.component == sample_document_component


@pytest.mark.django_db
def test_create_document_raw_data_missing_name(
    authenticated_api_client,
    sample_document_component,
):
    """Test raw data upload without required name parameter."""
    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    response = client.post(
        reverse("api-1:create_document") + f"?component_id={sample_document_component.id}&version=2.0",
        b"document content",
        content_type="application/octet-stream",
        **headers,
    )

    assert response.status_code == 400
    data = json.loads(response.content)
    assert "Name is required for raw data uploads" in data["detail"]


@pytest.mark.django_db
def test_create_document_component_not_found(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
):
    """Test upload with non-existent component."""
    client.force_login(sample_user)

    test_file = SimpleUploadedFile("test_document.pdf", b"test document content", content_type="application/pdf")

    response = client.post(
        reverse("api-1:create_document"),
        {"document_file": test_file, "component_id": "non-existent", "version": "1.0"},
        format="multipart",
    )

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "Document component not found" in data["detail"]


@pytest.mark.django_db
def test_create_document_wrong_component_type(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_team,  # noqa: F811
):
    """Test upload with wrong component type."""
    # Create a non-document component (SBOM type)
    component = Component.objects.create(
        name="Non-Document Component",
        team=sample_team,
        component_type=Component.ComponentType.SBOM,
    )

    client.force_login(sample_user)

    test_file = SimpleUploadedFile("test_document.pdf", b"test document content", content_type="application/pdf")

    response = client.post(
        reverse("api-1:create_document"),
        {"document_file": test_file, "component_id": component.id, "version": "1.0"},
        format="multipart",
    )

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "Document component not found" in data["detail"]


@pytest.mark.django_db
def test_create_document_forbidden(
    client: Client,
    guest_user: AbstractBaseUser,  # noqa: F811
    sample_document_component,
):
    """Test that users without permission cannot upload documents."""
    client.force_login(guest_user)

    test_file = SimpleUploadedFile("test_document.pdf", b"test document content", content_type="application/pdf")

    response = client.post(
        reverse("api-1:create_document"),
        {"document_file": test_file, "component_id": sample_document_component.id, "version": "1.0"},
        format="multipart",
    )

    assert response.status_code == 403
    data = json.loads(response.content)
    assert "Forbidden" in data["detail"]


@pytest.mark.django_db
def test_create_document_file_too_large(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document_component,
):
    """Test upload with file that exceeds size limit."""
    client.force_login(sample_user)

    # Create a file larger than 50MB
    large_content = b"x" * (51 * 1024 * 1024)  # 51MB
    test_file = SimpleUploadedFile("large_document.pdf", large_content, content_type="application/pdf")

    response = client.post(
        reverse("api-1:create_document"),
        {"document_file": test_file, "component_id": sample_document_component.id, "version": "1.0"},
        format="multipart",
    )

    assert response.status_code == 400
    data = json.loads(response.content)
    assert "File size must be less than 50MB" in data["detail"]


@pytest.mark.django_db
def test_get_document_success(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test successful document retrieval."""
    client.force_login(sample_user)

    response = client.get(reverse("api-1:get_document", kwargs={"document_id": sample_document.id}))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["id"] == sample_document.id
    assert data["name"] == sample_document.name
    assert data["version"] == sample_document.version
    assert data["component_id"] == sample_document.component.id
    assert data["source_display"] == "Manual Upload"


@pytest.mark.django_db
def test_get_document_not_found(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
):
    """Test getting non-existent document."""
    client.force_login(sample_user)

    response = client.get(reverse("api-1:get_document", kwargs={"document_id": "non-existent"}))

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "Document not found" in data["detail"]


@pytest.mark.django_db
def test_get_document_forbidden(
    client: Client,
    guest_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test that users without permission cannot get documents."""
    client.force_login(guest_user)

    response = client.get(reverse("api-1:get_document", kwargs={"document_id": sample_document.id}))

    assert response.status_code == 403
    data = json.loads(response.content)
    assert "Forbidden" in data["detail"]


@pytest.mark.django_db
def test_update_document_success(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test successful document metadata update."""
    client.force_login(sample_user)

    update_data = {
        "name": "Updated Document Name",
        "version": "2.0",
        "document_type": "manual",
        "description": "Updated description",
    }

    response = client.patch(
        reverse("api-1:update_document", kwargs={"document_id": sample_document.id}),
        json.dumps(update_data),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["name"] == "Updated Document Name"
    assert data["version"] == "2.0"
    assert data["document_type"] == "manual"
    assert data["description"] == "Updated description"

    # Verify document was updated in database
    document = Document.objects.get(id=sample_document.id)
    assert document.name == "Updated Document Name"
    assert document.version == "2.0"
    assert document.document_type == "manual"
    assert document.description == "Updated description"


@pytest.mark.django_db
def test_update_document_partial_update(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test partial document metadata update."""
    client.force_login(sample_user)

    # Only update name and version
    update_data = {
        "name": "Partially Updated Document",
        "version": "1.1",
    }

    response = client.patch(
        reverse("api-1:update_document", kwargs={"document_id": sample_document.id}),
        json.dumps(update_data),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["name"] == "Partially Updated Document"
    assert data["version"] == "1.1"
    # Other fields should remain unchanged
    assert data["document_type"] == sample_document.document_type
    assert data["description"] == sample_document.description


@pytest.mark.django_db
def test_update_document_not_found(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
):
    """Test updating non-existent document."""
    client.force_login(sample_user)

    update_data = {"name": "Updated Name"}

    response = client.patch(
        reverse("api-1:update_document", kwargs={"document_id": "non-existent"}),
        json.dumps(update_data),
        content_type="application/json",
    )

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "Document not found" in data["detail"]


@pytest.mark.django_db
def test_update_document_forbidden(
    client: Client,
    guest_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test that users without permission cannot update documents."""
    client.force_login(guest_user)

    update_data = {"name": "Updated Name"}

    response = client.patch(
        reverse("api-1:update_document", kwargs={"document_id": sample_document.id}),
        json.dumps(update_data),
        content_type="application/json",
    )

    assert response.status_code == 403
    data = json.loads(response.content)
    assert "Only owners and admins can update documents" in data["detail"]


@pytest.mark.django_db
def test_create_document_with_s3_error(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document_component,
):
    """Test upload handling when S3 raises an error."""
    create_documents_api_mock(mocker, scenario="upload_error")

    client.force_login(sample_user)

    test_file = SimpleUploadedFile("test_document.pdf", b"test document content", content_type="application/pdf")

    response = client.post(
        reverse("api-1:create_document"),
        {"document_file": test_file, "component_id": sample_document_component.id, "version": "1.0"},
        format="multipart",
    )

    assert response.status_code == 400
    data = json.loads(response.content)
    assert "Invalid request" in data["detail"]


@pytest.mark.django_db
def test_create_document_with_access_token(
    mocker: MockerFixture,
    authenticated_api_client,
    sample_document_component,
):
    """Test document upload using access token authentication."""
    create_documents_api_mock(mocker, scenario="success")

    client, access_token = authenticated_api_client
    headers = get_api_headers(access_token)

    test_file = SimpleUploadedFile("test_document.pdf", b"test document content", content_type="application/pdf")

    response = client.post(
        reverse("api-1:create_document"),
        {"document_file": test_file, "component_id": sample_document_component.id, "version": "1.0"},
        format="multipart",
        **headers,
    )

    assert response.status_code == 201
    data = json.loads(response.content)
    assert "id" in data


@pytest.mark.django_db
def test_get_document_public_access(
    client: Client,
    sample_team,  # noqa: F811
):
    """Test getting public document without authentication."""
    # Create a public document component
    public_component = Component.objects.create(
        name="Public Document Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
        visibility=Component.Visibility.PUBLIC,
    )

    public_document = Document.objects.create(
        name="Public Document",
        version="1.0",
        document_filename="public_doc.pdf",
        component=public_component,
        source="manual_upload",
    )

    # The current API requires authentication, so let's create a user and authenticate
    # This test verifies public documents can be accessed by any authenticated user
    from django.contrib.auth import get_user_model

    User = get_user_model()
    temp_user = User.objects.create_user(username="tempuser", password="temppass")
    client.force_login(temp_user)

    response = client.get(reverse("api-1:get_document", kwargs={"document_id": public_document.id}))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["id"] == public_document.id
    assert data["name"] == public_document.name


@pytest.mark.django_db
def test_delete_document_success(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test successful document deletion."""
    client.force_login(sample_user)

    response = client.delete(reverse("api-1:delete_document", kwargs={"document_id": sample_document.id}))

    assert response.status_code == 204

    # Verify document was deleted
    assert not Document.objects.filter(id=sample_document.id).exists()


@pytest.mark.django_db
def test_delete_document_not_found(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
):
    """Test deleting non-existent document."""
    client.force_login(sample_user)

    response = client.delete(reverse("api-1:delete_document", kwargs={"document_id": "non-existent"}))

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "Document not found" in data["detail"]


@pytest.mark.django_db
def test_delete_document_forbidden(
    client: Client,
    guest_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test that users without permission cannot delete documents."""
    client.force_login(guest_user)

    response = client.delete(reverse("api-1:delete_document", kwargs={"document_id": sample_document.id}))

    assert response.status_code == 403
    data = json.loads(response.content)
    assert "Only owners and admins can delete documents" in data["detail"]


@pytest.mark.django_db
def test_delete_document_member_can_delete(
    client: Client,
    guest_user: AbstractBaseUser,  # noqa: F811
    sample_document,
    sample_team,  # noqa: F811
):
    """Test that team members with admin role can delete documents."""
    # Add guest user as admin to the team
    Member.objects.create(
        user=guest_user,
        team=sample_team,
        role="admin",
    )

    client.force_login(guest_user)

    response = client.delete(reverse("api-1:delete_document", kwargs={"document_id": sample_document.id}))

    assert response.status_code == 204

    # Verify document was deleted
    assert not Document.objects.filter(id=sample_document.id).exists()


@pytest.mark.django_db
def test_download_document_public_success(
    mocker: MockerFixture,
    client: Client,
    sample_team,  # noqa: F811
):
    """Test successful public document download without authentication."""
    create_documents_api_mock(mocker, scenario="success")

    # Create a public document component
    public_component = Component.objects.create(
        name="Public Document Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
        is_public=True,
    )

    public_document = Document.objects.create(
        name="Public Document",
        version="1.0",
        document_filename="public_doc.pdf",
        component=public_component,
        source="manual_upload",
        content_type="application/pdf",
    )

    response = client.get(reverse("api-1:download_document", kwargs={"document_id": public_document.id}))

    assert response.status_code == 200
    assert response.content == b"test document content"
    assert response["Content-Type"] == "application/pdf"
    assert f'attachment; filename="{public_document.name}"' in response["Content-Disposition"]


@pytest.mark.django_db
def test_download_document_private_success(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test successful private document download with authentication."""
    create_documents_api_mock(mocker, scenario="success")

    client.force_login(sample_user)

    response = client.get(reverse("api-1:download_document", kwargs={"document_id": sample_document.id}))

    assert response.status_code == 200
    assert response.content == b"test document content"
    assert response["Content-Type"] == "application/pdf"
    assert f'attachment; filename="{sample_document.name}"' in response["Content-Disposition"]


@pytest.mark.django_db
def test_download_document_private_forbidden(
    client: Client,
    sample_document,
):
    """Test that private documents cannot be downloaded without authentication."""
    response = client.get(reverse("api-1:download_document", kwargs={"document_id": sample_document.id}))

    assert response.status_code == 403
    data = json.loads(response.content)
    assert "Access denied" in data["detail"]


@pytest.mark.django_db
def test_download_document_not_found(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
):
    """Test downloading non-existent document."""
    client.force_login(sample_user)

    response = client.get(reverse("api-1:download_document", kwargs={"document_id": "non-existent"}))

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "Document not found" in data["detail"]


@pytest.mark.django_db
def test_download_document_file_not_found(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test download when S3 file doesn't exist."""
    create_documents_api_mock(mocker, scenario="not_found")

    client.force_login(sample_user)

    response = client.get(reverse("api-1:download_document", kwargs={"document_id": sample_document.id}))

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "Document file not found" in data["detail"]


@pytest.mark.django_db
def test_download_document_s3_error(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test download handling when S3 raises an error."""
    create_documents_api_mock(mocker, scenario="download_error")

    client.force_login(sample_user)

    response = client.get(reverse("api-1:download_document", kwargs={"document_id": sample_document.id}))

    assert response.status_code == 500
    data = json.loads(response.content)
    assert "Error retrieving document" in data["detail"]


@pytest.mark.django_db
def test_download_document_with_fallback_filename(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document_component,
):
    """Test download with document that has no name (fallback to document_id)."""
    create_documents_api_mock(mocker, scenario="success")

    # Create document with empty name
    document = Document.objects.create(
        name="",
        version="1.0",
        document_filename="test_file.pdf",
        component=sample_document_component,
        source="manual_upload",
        content_type="application/pdf",
        file_size=1024,
    )

    client.force_login(sample_user)

    response = client.get(reverse("api-1:download_document", kwargs={"document_id": document.id}))

    assert response.status_code == 200
    assert response.content == b"test document content"
    assert f'attachment; filename="document_{document.id}"' in response["Content-Disposition"]


@pytest.mark.django_db
def test_download_document_default_content_type(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document_component,
):
    """Test download with document that has no content_type."""
    create_documents_api_mock(mocker, scenario="success")

    # Create document with no content_type
    document = Document.objects.create(
        name="Test Document",
        version="1.0",
        document_filename="test_file.pdf",
        component=sample_document_component,
        source="manual_upload",
        content_type="",
        file_size=1024,
    )

    client.force_login(sample_user)

    response = client.get(reverse("api-1:download_document", kwargs={"document_id": document.id}))

    assert response.status_code == 200
    assert response.content == b"test document content"
    assert response["Content-Type"] == "application/octet-stream"
