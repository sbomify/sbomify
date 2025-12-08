"""Tests for documents view functions."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client, override_settings
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.fixtures import guest_user, sample_user  # noqa: F401
from sbomify.apps.core.tests.s3_fixtures import create_documents_views_mock
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.fixtures import sample_team  # noqa: F401
from sbomify.apps.teams.models import Member

from ..models import Document


@pytest.fixture
def sample_document_component(sample_team, sample_user):
    """Create a sample document component for testing."""
    # Add sample_user as owner to the team for proper permissions
    Member.objects.get_or_create(
        user=sample_user,
        team=sample_team,
        defaults={"role": "owner"}
    )

    return Component.objects.create(
        name="Test Document Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
        is_public=False,
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


@pytest.fixture
def public_document_component(sample_team):
    """Create a public document component for testing."""
    return Component.objects.create(
        name="Public Document Component",
        team=sample_team,
        component_type=Component.ComponentType.DOCUMENT,
        is_public=True,
    )


@pytest.fixture
def public_document(public_document_component):
    """Create a public document for testing."""
    return Document.objects.create(
        name="Public Document",
        version="1.0",
        document_filename="public_doc.pdf",
        component=public_document_component,
        source="manual_upload",
        content_type="application/pdf",
        file_size=2048,
    )


@pytest.mark.django_db
@override_settings(
    DJANGO_VITE={
        "default": {
            "dev_mode": False,
            "manifest_path": "/nonexistent/manifest.json",  # Force it to not load assets
            "static_url_prefix": "/static/",
        }
    }
)
def test_document_details_private_success(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test successful access to private document details."""
    # Try to prevent vite asset loading errors by mocking the template loader
    with patch('django_vite.core.asset_loader.DjangoViteAssetLoader.instance') as mock_loader:
        # Mock the asset loader to return empty manifests
        mock_instance = MagicMock()
        mock_instance.manifest = MagicMock()
        mock_instance.manifest.get.return_value = None
        mock_instance.generate_vite_asset.return_value = ""
        mock_loader.return_value = mock_instance

        client.force_login(sample_user)

        response = client.get(
            reverse("documents:document_details", kwargs={"document_id": sample_document.id})
        )

        assert response.status_code == 200
        assert b"Test Document" in response.content
        assert "document" in response.context
        assert response.context["document"] == sample_document


@pytest.mark.django_db
def test_document_details_private_not_found(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
):
    """Test accessing non-existent private document."""
    client.force_login(sample_user)

    response = client.get(
        reverse("documents:document_details", kwargs={"document_id": "non-existent"})
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_document_details_private_unauthenticated(
    client: Client,
    sample_document,
):
    """Test that unauthenticated users are redirected to login."""
    response = client.get(
        reverse("documents:document_details", kwargs={"document_id": sample_document.id})
    )

    assert response.status_code == 302
    assert "/login" in response.url


@pytest.mark.django_db
def test_document_details_private_forbidden(
    client: Client,
    guest_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test that users without permission cannot access private document details."""
    client.force_login(guest_user)

    response = client.get(
        reverse("documents:document_details", kwargs={"document_id": sample_document.id})
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_document_details_public_success(
    client: Client,
    public_document,
):
    """Test successful access to public document details."""
    response = client.get(
        reverse("documents:document_details_public", kwargs={"document_id": public_document.id})
    )

    assert response.status_code == 200
    assert b"Public Document" in response.content
    assert "document" in response.context
    assert response.context["document"] == public_document


@pytest.mark.django_db
def test_document_details_public_not_found(
    client: Client,
):
    """Test accessing non-existent public document."""
    response = client.get(
        reverse("documents:document_details_public", kwargs={"document_id": "non-existent"})
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_document_details_public_private_document(
    client: Client,
    sample_document,
):
    """Test that private documents are not accessible via public URL."""
    response = client.get(
        reverse("documents:document_details_public", kwargs={"document_id": sample_document.id})
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_document_details_public_shows_trust_center_link_for_global(
    client: Client,
    public_document,
):
    """Workspace-wide documents should show a back link to the Trust Center."""
    public_document.component.is_global = True
    public_document.component.save(update_fields=["is_global"])

    response = client.get(
        reverse("documents:document_details_public", kwargs={"document_id": public_document.id})
    )

    assert response.status_code == 200
    assert b"Back to Trust Center" in response.content
    expected_url = reverse("core:workspace_public", kwargs={"workspace_key": public_document.component.team.key})
    assert expected_url.encode() in response.content


@pytest.mark.django_db
def test_document_details_public_hides_trust_center_link_for_project_scoped(
    client: Client,
    public_document,
):
    """Non-workspace documents should not render the back-to-trust-center link."""
    public_document.component.is_global = False
    public_document.component.save(update_fields=["is_global"])

    response = client.get(
        reverse("documents:document_details_public", kwargs={"document_id": public_document.id})
    )

    assert response.status_code == 200
    assert b"Back to Trust Center" not in response.content


@pytest.mark.django_db
def test_document_download_success(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test successful document download."""
    create_documents_views_mock(mocker, scenario="success")

    client.force_login(sample_user)

    response = client.get(
        reverse("documents:document_download", kwargs={"document_id": sample_document.id})
    )

    assert response.status_code == 200
    assert response.content == b"test document content"
    assert response["Content-Type"] == "application/pdf"
    assert f'attachment; filename="{sample_document.name}"' in response["Content-Disposition"]


@pytest.mark.django_db
def test_document_download_public_success(
    mocker: MockerFixture,
    client: Client,
    public_document,
):
    """Test successful public document download without authentication."""
    create_documents_views_mock(mocker, scenario="success")

    response = client.get(
        reverse("documents:document_download", kwargs={"document_id": public_document.id})
    )

    assert response.status_code == 200
    assert response.content == b"test document content"
    assert response["Content-Type"] == "application/pdf"
    assert f'attachment; filename="{public_document.name}"' in response["Content-Disposition"]


@pytest.mark.django_db
def test_document_download_not_found(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
):
    """Test downloading non-existent document."""
    client.force_login(sample_user)

    response = client.get(
        reverse("documents:document_download", kwargs={"document_id": "non-existent"})
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_document_download_forbidden(
    client: Client,
    guest_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test that users without permission cannot download documents."""
    client.force_login(guest_user)

    response = client.get(
        reverse("documents:document_download", kwargs={"document_id": sample_document.id})
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_document_download_private_document_public_access_denied(
    client: Client,
    sample_document,
):
    """Test that private documents cannot be downloaded without authentication."""
    response = client.get(
        reverse("documents:document_download", kwargs={"document_id": sample_document.id})
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_document_download_s3_file_not_found(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test download when S3 file doesn't exist."""
    create_documents_views_mock(mocker, scenario="not_found")

    client.force_login(sample_user)

    response = client.get(
        reverse("documents:document_download", kwargs={"document_id": sample_document.id})
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_document_download_s3_error(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test download when S3 raises an error."""
    create_documents_views_mock(mocker, scenario="download_error")

    client.force_login(sample_user)

    response = client.get(
        reverse("documents:document_download", kwargs={"document_id": sample_document.id})
    )

    assert response.status_code == 500


@pytest.mark.django_db
def test_document_download_with_filename_fallback(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document_component,
):
    """Test download with document that has no name (fallback to document_id)."""
    create_documents_views_mock(mocker, scenario="success")

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

    response = client.get(
        reverse("documents:document_download", kwargs={"document_id": document.id})
    )

    assert response.status_code == 200
    assert response.content == b"test document content"
    assert f'attachment; filename="document_{document.id}"' in response["Content-Disposition"]


@pytest.mark.django_db
def test_document_download_default_content_type(
    mocker: MockerFixture,
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document_component,
):
    """Test download with document that has no content_type."""
    create_documents_views_mock(mocker, scenario="success")

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

    response = client.get(
        reverse("documents:document_download", kwargs={"document_id": document.id})
    )

    assert response.status_code == 200
    assert response.content == b"test document content"
    assert response["Content-Type"] == "application/octet-stream"


@pytest.mark.django_db
@override_settings(
    DJANGO_VITE={
        "default": {
            "dev_mode": False,
            "manifest_path": "/nonexistent/manifest.json",  # Force it to not load assets
            "static_url_prefix": "/static/",
        }
    }
)
def test_document_details_private_template_context(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test that private document details view provides correct template context."""
    # Try to prevent vite asset loading errors by mocking the template loader
    with patch('django_vite.core.asset_loader.DjangoViteAssetLoader.instance') as mock_loader:
        # Mock the asset loader to return empty manifests
        mock_instance = MagicMock()
        mock_instance.manifest = MagicMock()
        mock_instance.manifest.get.return_value = None
        mock_instance.generate_vite_asset.return_value = ""
        mock_loader.return_value = mock_instance

        client.force_login(sample_user)

        response = client.get(
            reverse("documents:document_details", kwargs={"document_id": sample_document.id})
        )

        assert response.status_code == 200
        assert "document" in response.context
        assert "APP_BASE_URL" in response.context
        assert response.context["document"] == sample_document


@pytest.mark.django_db
def test_document_details_public_template_context(
    client: Client,
    public_document,
):
    """Test that public document details view provides correct template context."""
    response = client.get(
        reverse("documents:document_details_public", kwargs={"document_id": public_document.id})
    )

    assert response.status_code == 200
    assert "document" in response.context
    assert "APP_BASE_URL" in response.context
    assert response.context["document"] == public_document


@pytest.mark.django_db
@override_settings(
    DJANGO_VITE={
        "default": {
            "dev_mode": False,
            "manifest_path": "/nonexistent/manifest.json",  # Force it to not load assets
            "static_url_prefix": "/static/",
        }
    }
)
def test_document_details_private_template_used(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_document,
):
    """Test that private document details view uses correct template."""
    # Try to prevent vite asset loading errors by mocking the template loader
    with patch('django_vite.core.asset_loader.DjangoViteAssetLoader.instance') as mock_loader:
        # Mock the asset loader to return empty manifests
        mock_instance = MagicMock()
        mock_instance.manifest = MagicMock()
        mock_instance.manifest.get.return_value = None
        mock_instance.generate_vite_asset.return_value = ""
        mock_loader.return_value = mock_instance

        client.force_login(sample_user)

        response = client.get(
            reverse("documents:document_details", kwargs={"document_id": sample_document.id})
        )

        assert response.status_code == 200
        assert "documents/document_details_private.html.j2" in [t.name for t in response.templates]


@pytest.mark.django_db
def test_document_details_public_template_used(
    client: Client,
    public_document,
):
    """Test that public document details view uses correct template."""
    response = client.get(
        reverse("documents:document_details_public", kwargs={"document_id": public_document.id})
    )

    assert response.status_code == 200
    assert "documents/document_details_public.html.j2" in [t.name for t in response.templates]
