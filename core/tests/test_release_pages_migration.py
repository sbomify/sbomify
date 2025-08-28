"""
Tests for the release pages migration from Vue to Django Templates.
Uses proper pytest fixtures for account management and data setup.
"""

import pytest
import os
import json
from django.test import Client
from django.urls import reverse

from core.models import Product, Release, Component, ReleaseArtifact
from teams.models import Member
from sboms.models import SBOM
from documents.models import Document
from sboms.tests.fixtures import (  # noqa: F401
    sample_product,
    sample_component,
    sample_sbom,
    sample_access_token,
)
from teams.fixtures import sample_team_with_owner_member  # noqa: F401
from core.tests.fixtures import sample_user  # noqa: F401
from sboms.tests.test_views import setup_test_session


@pytest.fixture
def sample_document(sample_component: Component):  # noqa: F811
    """Create a sample document for testing."""
    return Document.objects.create(
        name="Test Document",
        version="1.0.0",
        document_filename="test_file.vex",
        component=sample_component,
        source="manual_upload",
        content_type="application/json",
        file_size=1024,
        document_type="vex",
    )


@pytest.fixture
def sample_release(sample_product: Product):  # noqa: F811
    """Create a sample release for testing."""
    return Release.objects.create(
        name='v1.0.0',
        product=sample_product,
        description='Test release description',
        is_prerelease=False
    )


@pytest.fixture
def sample_release_artifacts(sample_release: Release, sample_sbom: SBOM, sample_document: Document):  # noqa: F811
    """Create sample release artifacts for testing."""
    sbom_artifact = ReleaseArtifact.objects.create(
        sbom=sample_sbom,
        release=sample_release
    )
    document_artifact = ReleaseArtifact.objects.create(
        document=sample_document,
        release=sample_release
    )
    return sbom_artifact, document_artifact


# =============================================================================
# RELEASE PAGES TESTS
# =============================================================================


@pytest.mark.django_db
def test_public_release_details_page_renders(
    sample_release: Release,  # noqa: F811
    sample_product: Product,  # noqa: F811
):
    """Test that the public release details page renders correctly."""
    # Make the product public so the release can be accessed publicly
    sample_product.is_public = True
    sample_product.save()

    client = Client()
    url = reverse('core:release_details_public', args=[sample_product.id, sample_release.id])
    response = client.get(url)

    assert response.status_code == 200
    assert sample_release.name in response.content.decode()
    assert sample_release.description in response.content.decode()
    assert 'Artifacts in this Release' in response.content.decode()


@pytest.mark.django_db
def test_private_release_details_page_renders(
    sample_release: Release,  # noqa: F811
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that the private release details page renders correctly."""
    client = Client()

    # Login and setup session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    url = reverse('core:release_details', args=[sample_product.id, sample_release.id])
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()
    assert sample_release.name in content
    assert sample_release.description in content
    # The page should render successfully, even if there are no artifacts
    assert 'Release Details' in content or sample_release.name in content


@pytest.mark.django_db
def test_release_modal_component_present(
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that the release modal component is present on pages with CRUD permissions."""
    client = Client()

    # Login and setup session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    # Test product releases page
    url = reverse('core:product_releases', args=[sample_product.id])
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    # Check modal is present
    assert 'id="createReleaseModal"' in content
    assert 'Create Release' in content
    assert 'id="createReleaseForm"' in content

    # Check form fields are present
    assert 'name="name"' in content
    assert 'name="description"' in content
    assert 'name="is_prerelease"' in content


@pytest.mark.django_db
def test_all_releases_modal_has_product_selector(
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that the all-releases page modal includes product selection."""
    client = Client()

    # Login and setup session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    # Test all releases dashboard
    url = reverse('core:releases_dashboard')
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode()

    # Check modal is present with product selector
    assert 'id="createReleaseModal"' in content
    assert 'name="product_id"' in content
    assert 'Select a product...' in content


# =============================================================================
# API INTEGRATION TESTS
# =============================================================================


@pytest.mark.django_db
def test_create_release_api_integration(
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test release creation through API (TypeScript functionality)."""
    client = Client()

    # Login and setup session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    # Test data
    release_data = {
        'name': 'v2.0.0',
        'description': 'New test release',
        'is_prerelease': True,
        'product_id': str(sample_product.id)
    }

    # Make API request (simulating TypeScript call)
    response = client.post(
        '/api/v1/releases',
        data=json.dumps(release_data),
        content_type='application/json'
    )

    assert response.status_code == 201

    # Verify release was created
    release = Release.objects.get(name='v2.0.0')
    assert release.description == 'New test release'
    assert release.is_prerelease is True
    assert release.product == sample_product


@pytest.mark.django_db
def test_edit_release_api_integration(
    sample_release: Release,  # noqa: F811
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test release editing through API (TypeScript functionality)."""
    client = Client()

    # Login and setup session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    # Test data for update
    update_data = {
        'name': 'v1.0.1',
        'description': 'Updated test release description',
        'is_prerelease': False
    }

    # Make API request (simulating TypeScript call)
    response = client.put(
        f'/api/v1/releases/{sample_release.id}',
        data=json.dumps(update_data),
        content_type='application/json'
    )

    assert response.status_code == 200

    # Verify release was updated
    sample_release.refresh_from_db()
    assert sample_release.name == 'v1.0.1'
    assert sample_release.description == 'Updated test release description'
    assert sample_release.is_prerelease is False


@pytest.mark.django_db
def test_delete_release_api_integration(
    sample_release: Release,  # noqa: F811
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test release deletion through API (TypeScript functionality)."""
    client = Client()

    # Login and setup session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    release_id = sample_release.id

    # Make API request (simulating TypeScript call)
    response = client.delete(f'/api/v1/releases/{release_id}')

    assert response.status_code == 204

    # Verify release was deleted
    assert not Release.objects.filter(id=release_id).exists()


@pytest.mark.django_db
def test_release_form_validation_errors(
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test release form validation through API."""
    client = Client()

    # Login and setup session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    # Test data with missing required fields
    invalid_data = {
        'description': 'Missing name field',
        'product_id': str(sample_product.id)
    }

    # Make API request (simulating TypeScript call)
    response = client.post(
        '/api/v1/releases',
        data=json.dumps(invalid_data),
        content_type='application/json'
    )

    # Should return validation error (422 Unprocessable Entity in Django Ninja)
    assert response.status_code == 422


@pytest.mark.django_db
def test_duplicate_release_name_validation(
    sample_release: Release,  # noqa: F811
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that duplicate release names are rejected."""
    client = Client()

    # Login and setup session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    # Try to create release with same name
    duplicate_data = {
        'name': sample_release.name,  # Same name as existing release
        'description': 'Duplicate name test',
        'product_id': str(sample_product.id)
    }

    # Make API request (simulating TypeScript call)
    response = client.post(
        '/api/v1/releases',
        data=json.dumps(duplicate_data),
        content_type='application/json'
    )

    # Should return validation error
    assert response.status_code == 400


@pytest.mark.django_db
def test_full_crud_workflow_integration(
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test complete CRUD workflow for releases."""
    client = Client()

    # Login and setup session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    # 1. Create release
    create_data = {
        'name': 'v1.0.0',
        'description': 'Initial release',
        'is_prerelease': False,
        'product_id': str(sample_product.id)
    }

    response = client.post(
        '/api/v1/releases',
        data=json.dumps(create_data),
        content_type='application/json'
    )
    assert response.status_code == 201

    release_data = response.json()
    release_id = release_data['id']

    # 2. Read/verify creation
    release = Release.objects.get(id=release_id)
    assert release.name == 'v1.0.0'
    assert release.description == 'Initial release'
    assert release.is_prerelease is False

    # 3. Update release
    update_data = {
        'name': 'v1.0.1',
        'description': 'Updated release',
        'is_prerelease': True
    }

    response = client.put(
        f'/api/v1/releases/{release_id}',
        data=json.dumps(update_data),
        content_type='application/json'
    )
    assert response.status_code == 200

    # 4. Verify update
    release.refresh_from_db()
    assert release.name == 'v1.0.1'
    assert release.description == 'Updated release'
    assert release.is_prerelease is True

    # 5. Delete release
    response = client.delete(f'/api/v1/releases/{release_id}')
    assert response.status_code == 204

    # 6. Verify deletion
    assert not Release.objects.filter(id=release_id).exists()
