"""Tests for Release API endpoints."""

from __future__ import annotations

import json
import os

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_access_token,
    sample_component,
    sample_product,
    sample_sbom,
)
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.fixtures import sample_team_with_guest_member, sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member


@pytest.fixture
def sample_document(sample_component: Component):  # noqa: F811
    """Create a sample document for testing."""
    return Document.objects.create(
        name="Test Document",
        version="1.0",
        document_filename="test_file.pdf",
        component=sample_component,
        source="manual_upload",
        content_type="application/pdf",
        file_size=1024,
        document_type="license",
    )


# =============================================================================
# RELEASE CRUD TESTS
# =============================================================================


@pytest.mark.django_db
def test_create_release_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful release creation."""
    client = Client()
    url = reverse("api-1:create_release")

    payload = {"name": "v1.0.0", "product_id": str(sample_product.id)}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "v1.0.0"
    assert data["product_id"] == str(sample_product.id)
    assert data["is_latest"] is False
    assert "id" in data
    assert "created_at" in data
    assert "released_at" in data

    # Verify release was created in database
    release = Release.objects.get(id=data["id"])
    assert release.name == "v1.0.0"
    assert release.product_id == sample_product.id
    assert release.created_at == release.released_at


@pytest.mark.django_db
def test_create_release_with_custom_dates(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test creating a release with custom created and release dates."""
    from datetime import datetime, timezone

    client = Client()
    url = reverse("api-1:create_release")

    custom_created = datetime(2023, 5, 10, 9, 0, tzinfo=timezone.utc)
    custom_released = datetime(2023, 5, 12, 10, 30, tzinfo=timezone.utc)
    payload = {
        "name": "v2.0.0",
        "product_id": str(sample_product.id),
        "created_at": custom_created.isoformat(),
        "released_at": custom_released.isoformat(),
    }

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created_at"].startswith("2023-05-10")
    assert data["released_at"].startswith("2023-05-12")

    release = Release.objects.get(id=data["id"])
    assert release.created_at == custom_created
    assert release.released_at == custom_released


@pytest.mark.django_db
def test_create_release_duplicate_name(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test release creation with duplicate name fails."""
    client = Client()
    url = reverse("api-1:create_release")

    # Create first release
    Release.objects.create(product=sample_product, name="v1.0.0")

    payload = {"name": "v1.0.0", "product_id": str(sample_product.id)}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.django_db
def test_create_release_named_latest_fails(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that manually creating a release named 'latest' fails."""
    client = Client()
    url = reverse("api-1:create_release")

    payload = {"name": "latest", "product_id": str(sample_product.id)}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 400
    assert "Cannot create release with name 'latest'" in response.json()["detail"]


@pytest.mark.django_db
def test_list_releases(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test listing releases for a product."""
    client = Client()
    url = reverse("api-1:list_all_releases") + f"?product_id={sample_product.id}"

    # Create test releases
    release1 = Release.objects.create(product=sample_product, name="v1.0.0")
    release2 = Release.objects.create(product=sample_product, name="v2.0.0")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data
    # Now expect 3 releases: 2 manual + 1 automatic "latest" release
    assert len(data["items"]) == 3

    release_names = [r["name"] for r in data["items"]]
    release_ids = [r["id"] for r in data["items"]]

    # Verify the manual releases are present
    assert release1.id in release_ids
    assert release2.id in release_ids
    assert "v1.0.0" in release_names
    assert "v2.0.0" in release_names

    # Verify the automatic latest release was created
    assert "latest" in release_names
    latest_release_data = [r for r in data["items"] if r["name"] == "latest"][0]
    assert latest_release_data["is_latest"] is True


@pytest.mark.django_db
def test_list_releases_public_product_no_auth(sample_product):  # noqa: F811
    """Test listing releases for a public product without authentication."""
    from django.test import Client
    from django.urls import reverse

    from sbomify.apps.core.models import Release

    # Make product public
    sample_product.is_public = True
    sample_product.save()

    # Create test releases
    release1 = Release.objects.create(product=sample_product, name="v1.0.0")
    release2 = Release.objects.create(product=sample_product, name="v2.0.0")

    client = Client()
    url = reverse("api-1:list_all_releases") + f"?product_id={sample_product.id}"

    # Should work without authentication for public products
    response = client.get(url)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data
    # Should have 3 releases: 2 manual + 1 automatic "latest" release
    assert len(data["items"]) == 3

    release_names = [r["name"] for r in data["items"]]
    release_ids = [r["id"] for r in data["items"]]

    # Verify the manual releases are present
    assert release1.id in release_ids
    assert release2.id in release_ids
    assert "v1.0.0" in release_names
    assert "v2.0.0" in release_names

    # Verify the automatic latest release was created
    assert "latest" in release_names


@pytest.mark.django_db
def test_list_releases_pagination(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that releases endpoint supports pagination."""
    client = Client()
    url = reverse("api-1:list_all_releases") + f"?product_id={sample_product.id}"

    # Create many releases to test pagination
    for i in range(25):
        Release.objects.create(product=sample_product, name=f"v{i}.0.0")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test first page with default page size
    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data

    pagination = data["pagination"]
    assert pagination["page"] == 1
    assert pagination["page_size"] == 15
    assert pagination["total"] == 26  # 25 manual + 1 automatic "latest" release
    assert pagination["total_pages"] == 2
    assert pagination["has_previous"] is False
    assert pagination["has_next"] is True
    assert len(data["items"]) == 15

    # Test second page
    response = client.get(
        url + "&page=2",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    pagination = data["pagination"]
    assert pagination["page"] == 2
    assert pagination["has_previous"] is True
    assert pagination["has_next"] is False
    assert len(data["items"]) == 11  # Remaining items on last page

    # Test custom page size
    response = client.get(
        url + "&page_size=10",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    pagination = data["pagination"]
    assert pagination["page_size"] == 10
    assert pagination["total_pages"] == 3
    assert len(data["items"]) == 10


@pytest.mark.django_db
def test_get_release_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test getting a specific release."""
    client = Client()
    release = Release.objects.create(product=sample_product, name="v1.0.0")
    url = reverse("api-1:get_release", kwargs={"release_id": release.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == release.id
    assert data["name"] == "v1.0.0"
    assert data["product_id"] == str(sample_product.id)


@pytest.mark.django_db
def test_update_release_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful release update."""
    client = Client()
    release = Release.objects.create(product=sample_product, name="v1.0.0")
    url = reverse("api-1:update_release", kwargs={"release_id": release.id})

    payload = {"name": "v1.1.0"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "v1.1.0"

    # Verify update in database
    release.refresh_from_db()
    assert release.name == "v1.1.0"


@pytest.mark.django_db
def test_update_latest_release_fails(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that updating a 'latest' release fails."""
    client = Client()
    # Create latest release directly (simulating auto-creation)
    release = Release.objects.create(product=sample_product, name="latest", is_latest=True)
    url = reverse("api-1:update_release", kwargs={"release_id": release.id})

    payload = {"name": "v1.0.0"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 400
    assert "automatically managed" in response.json()["detail"]


@pytest.mark.django_db
def test_patch_release_with_unchanged_name(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that patching a release with the same name doesn't trigger 'already exists' error."""
    client = Client()
    release = Release.objects.create(product=sample_product, name="v1.0.0", description="Original description")
    url = reverse("api-1:patch_release", kwargs={"release_id": release.id})

    # PATCH with same name but different description - should succeed
    payload = {"name": "v1.0.0", "description": "Updated description"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "v1.0.0"
    assert data["description"] == "Updated description"

    # Verify in database
    release.refresh_from_db()
    assert release.name == "v1.0.0"
    assert release.description == "Updated description"


@pytest.mark.django_db
def test_patch_release_with_no_changes(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that patching a release with no actual changes works correctly."""
    client = Client()
    release = Release.objects.create(product=sample_product, name="v1.0.0", description="Test description")
    url = reverse("api-1:patch_release", kwargs={"release_id": release.id})

    # PATCH with exact same values - should succeed and not trigger database save
    payload = {"name": "v1.0.0", "description": "Test description", "is_prerelease": False}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "v1.0.0"
    assert data["description"] == "Test description"
    assert data["is_prerelease"] is False

    # Verify in database - values should remain the same
    release.refresh_from_db()
    assert release.name == "v1.0.0"
    assert release.description == "Test description"
    assert release.is_prerelease is False


@pytest.mark.django_db
def test_latest_release_created_on_releases_list_access(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that accessing product releases creates a latest release if it doesn't exist."""
    client = Client()

    # Verify no releases exist initially
    assert Release.objects.filter(product=sample_product).count() == 0

    # Access the product releases via API
    url = reverse("api-1:list_all_releases") + f"?product_id={sample_product.id}"

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200

    # Verify latest release was created and is in the response
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "latest"
    assert data["items"][0]["is_latest"] is True

    # Verify in database
    latest_releases = Release.objects.filter(product=sample_product, is_latest=True)
    assert latest_releases.count() == 1


@pytest.mark.django_db
def test_latest_release_not_duplicated_on_repeated_access(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that accessing a product multiple times doesn't create duplicate latest releases."""
    client = Client()

    # Verify no releases exist initially
    assert Release.objects.filter(product=sample_product).count() == 0

    url = reverse("api-1:get_product", kwargs={"product_id": sample_product.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Access the product multiple times
    for _ in range(3):
        response = client.get(
            url,
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 200

    # Verify only one latest release exists
    latest_releases = Release.objects.filter(product=sample_product, is_latest=True)
    assert latest_releases.count() == 1

    # Verify total releases count is still 1
    assert Release.objects.filter(product=sample_product).count() == 1


@pytest.mark.django_db
def test_delete_release_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful release deletion."""
    client = Client()
    release = Release.objects.create(product=sample_product, name="v1.0.0")
    url = reverse("api-1:delete_release", kwargs={"release_id": release.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.delete(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 204

    # Verify deletion in database
    assert not Release.objects.filter(id=release.id).exists()


@pytest.mark.django_db
def test_delete_latest_release_fails(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that deleting a 'latest' release fails."""
    client = Client()
    # Create latest release directly (simulating auto-creation)
    release = Release.objects.create(product=sample_product, name="latest", is_latest=True)
    url = reverse("api-1:delete_release", kwargs={"release_id": release.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.delete(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 400
    assert "automatically managed" in response.json()["detail"]


# =============================================================================
# RELEASE ARTIFACT MANAGEMENT TESTS
# =============================================================================


@pytest.mark.django_db
def test_add_sbom_to_release(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test adding an SBOM to a release."""
    client = Client()

    # Ensure component is part of the product and same team
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Ensure SBOM belongs to the component
    sample_sbom.component = sample_component
    sample_sbom.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    url = reverse("api-1:add_artifacts_to_release", kwargs={"release_id": release.id})

    payload = {"sbom_id": sample_sbom.id}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["artifact_type"] == "sbom"
    assert data["artifact_name"] == sample_sbom.name

    # Verify artifact was added to database
    assert ReleaseArtifact.objects.filter(release=release, sbom=sample_sbom, document=None).exists()


@pytest.mark.django_db
def test_add_document_to_release(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_document: Document,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test adding a document to a release."""
    client = Client()

    # Ensure component is part of the product and same team
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Ensure document belongs to the component
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    url = reverse("api-1:add_artifacts_to_release", kwargs={"release_id": release.id})

    payload = {"document_id": sample_document.id}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["artifact_type"] == "document"
    assert data["artifact_name"] == sample_document.name

    # Verify artifact was added to database
    assert ReleaseArtifact.objects.filter(release=release, sbom=None, document=sample_document).exists()


@pytest.mark.django_db
def test_remove_sbom_from_release(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test removing an SBOM from a release."""
    client = Client()

    # Ensure component is part of the product and same team
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Ensure SBOM belongs to the component
    sample_sbom.component = sample_component
    sample_sbom.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    artifact = ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)

    url = reverse("api-1:remove_artifact_from_release", kwargs={"release_id": release.id, "artifact_id": artifact.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.delete(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 204

    # Verify artifact was removed from database
    assert not ReleaseArtifact.objects.filter(release=release, sbom=sample_sbom).exists()


@pytest.mark.django_db
def test_remove_document_from_release(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_document: Document,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test removing a document from a release."""
    client = Client()

    # Ensure component is part of the product and same team
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Ensure document belongs to the component
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    artifact = ReleaseArtifact.objects.create(release=release, document=sample_document)

    url = reverse("api-1:remove_artifact_from_release", kwargs={"release_id": release.id, "artifact_id": artifact.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.delete(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 204

    # Verify artifact was removed from database
    assert not ReleaseArtifact.objects.filter(release=release, document=sample_document).exists()


# =============================================================================
# RELEASE SBOM DOWNLOAD TESTS
# =============================================================================


@pytest.mark.django_db
def test_download_release_sbom_success(
    mocker,
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    tmp_path,
):
    """Test downloading consolidated SBOM for a release."""
    client = Client()

    # IMPORTANT: Set product to public (required for SBOM generation)
    sample_product.is_public = True
    sample_product.save()

    # Create a mock SBOM file
    mock_package = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "timestamp": "2024-01-01T00:00:00Z",
            "component": {"type": "application", "name": sample_product.name, "version": "v1.0.0"},
        },
        "components": [],
    }

    # Create a mock file that will be returned by the mock function
    mock_file_path = tmp_path / f"{sample_product.name}-v1.0.0.cdx.json"
    mock_file_path.write_text(json.dumps(mock_package, indent=2))

    # Mock the SBOM package generator to return the file path
    mock_get_release_sbom_package = mocker.patch("sbomify.apps.core.apis.get_release_sbom_package")
    mock_get_release_sbom_package.return_value = mock_file_path

    # Ensure component is part of the product and same team
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Ensure SBOM belongs to the component
    sample_sbom.component = sample_component
    sample_sbom.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)

    url = reverse("api-1:download_release", kwargs={"release_id": release.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert f"attachment; filename={sample_product.name}-v1.0.0.cdx.json" in response["Content-Disposition"]

    # Verify the mock was called with correct parameters (release and temp_dir)
    mock_get_release_sbom_package.assert_called_once()
    call_args = mock_get_release_sbom_package.call_args
    assert call_args[0][0] == release  # First argument should be the release
    # Second argument should be a Path object (temp directory)

    # Verify response content
    data = response.json()
    assert data["bomFormat"] == "CycloneDX"
    assert data["metadata"]["component"]["name"] == sample_product.name


@pytest.mark.django_db
def test_download_release_sbom_no_artifacts(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test downloading SBOM for release with no artifacts returns 404."""
    client = Client()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    url = reverse("api-1:download_release", kwargs={"release_id": release.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 500  # Error generating SBOM from empty release
    assert "Error generating release SBOM" in response.json()["detail"]


# =============================================================================
# PERMISSION AND ACCESS CONTROL TESTS
# =============================================================================


@pytest.mark.django_db
def test_release_operations_require_authentication():
    """Test that release operations require authentication."""
    client = Client()

    # Create a product (will fail without authentication)
    url = reverse("api-1:create_release")
    payload = {"name": "v1.0.0", "product_id": "test"}

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_release_operations_require_team_member(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_team_with_guest_member: Member,  # noqa: F811
):
    """Test that release operations require proper team membership."""
    client = Client()
    url = reverse("api-1:create_release")

    payload = {"name": "v1.0.0", "product_id": str(sample_product.id)}

    # Set up authentication with different team
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_team_with_guest_member.team, sample_team_with_guest_member.user)

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 403  # Forbidden - not a member of this team


@pytest.mark.django_db
def test_guest_cannot_modify_releases(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_team_with_guest_member: Member,  # noqa: F811
):
    """Test that guest members cannot modify releases."""
    # Create a guest member in the same team as the product
    guest_member = sample_team_with_guest_member
    guest_member.team = sample_product.team
    guest_member.role = "guest"
    guest_member.save()

    client = Client()
    url = reverse("api-1:create_release")

    payload = {"name": "v1.0.0", "product_id": str(sample_product.id)}

    # Set up authentication as guest
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, guest_member.team, guest_member.user)

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 403  # Forbidden for guests


# =============================================================================
# VALIDATION TESTS
# =============================================================================


@pytest.mark.django_db
def test_add_duplicate_sbom_format_to_release(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that adding duplicate SBOM format from same component fails."""
    client = Client()

    # Ensure component is part of the product and same team
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Create two SBOMs with same format for same component (different versions to satisfy uniqueness)
    sbom1 = SBOM.objects.create(
        component=sample_component, format="cyclonedx", format_version="1.6", name="SBOM 1", version="1.0.0"
    )
    sbom2 = SBOM.objects.create(
        component=sample_component, format="cyclonedx", format_version="1.6", name="SBOM 2", version="2.0.0"
    )

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    # Add first SBOM successfully
    ReleaseArtifact.objects.create(release=release, sbom=sbom1)

    # Try to add second SBOM with same format
    url = reverse("api-1:add_artifacts_to_release", kwargs={"release_id": release.id})
    payload = {"sbom_id": sbom2.id}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 400
    assert "already contains an SBOM of format" in response.json()["detail"]


@pytest.mark.django_db
def test_add_sbom_from_different_team_fails(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that adding SBOM from different team fails."""
    from sbomify.apps.teams.models import Team

    client = Client()

    # Create a different team explicitly
    different_team = Team.objects.create(name="different team")

    # Ensure SBOM belongs to component from different team
    sample_component.team = different_team
    sample_component.save()
    sample_sbom.component = sample_component
    sample_sbom.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    url = reverse("api-1:add_artifacts_to_release", kwargs={"release_id": release.id})

    payload = {"sbom_id": sample_sbom.id}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 403  # SBOM belongs to a different team


@pytest.mark.django_db
def test_list_available_artifacts_for_release(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_document: Document,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test listing available artifacts for a release."""
    client = Client()

    # Ensure component is part of the product and same team
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Ensure artifacts belong to the component
    sample_sbom.component = sample_component
    sample_sbom.save()
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")
    url = reverse("api-1:list_release_artifacts", kwargs={"release_id": release.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()

    # Should have both SBOM and document
    assert len(data["items"]) == 2

    # Check SBOM data
    sbom_artifact = next((item for item in data["items"] if item["artifact_type"] == "sbom"), None)
    assert sbom_artifact is not None
    assert sbom_artifact["id"] == sample_sbom.id
    assert sbom_artifact["name"] == sample_sbom.name
    assert sbom_artifact["component"]["name"] == sample_component.name

    # Check document data
    doc_artifact = next((item for item in data["items"] if item["artifact_type"] == "document"), None)
    assert doc_artifact is not None
    assert doc_artifact["id"] == sample_document.id
    assert doc_artifact["name"] == sample_document.name
    assert doc_artifact["component"]["name"] == sample_component.name


@pytest.mark.django_db
def test_list_available_artifacts_excludes_existing(
    sample_product: Product,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_document: Document,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that available artifacts excludes those already in the release."""
    client = Client()

    # Ensure component is part of the product and same team
    sample_component.team = sample_product.team
    sample_component.save()
    # Get the project from the component (there should be one from our fixture)
    component_project = sample_component.projects.first()
    sample_product.projects.add(component_project)

    # Ensure artifacts belong to the component
    sample_sbom.component = sample_component
    sample_sbom.save()
    sample_document.component = sample_component
    sample_document.save()

    release = Release.objects.create(product=sample_product, name="v1.0.0")

    # Add SBOM to release (but not document)
    ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)

    url = reverse("api-1:list_release_artifacts", kwargs={"release_id": release.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()

    # Should only have document (SBOM should be excluded since it's already in release)
    assert len(data["items"]) == 1
    assert data["items"][0]["artifact_type"] == "document"
    assert data["items"][0]["id"] == sample_document.id


@pytest.mark.django_db
def test_update_release_dates(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test updating both release and created dates."""
    from datetime import datetime, timezone

    client = Client()

    # Create a release
    release = Release.objects.create(product=sample_product, name="v1.0.0")
    original_released = release.released_at
    original_created = release.created_at

    # Set a new date
    new_released = datetime(2023, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    new_created = datetime(2022, 12, 20, 9, 30, 0, tzinfo=timezone.utc)

    url = reverse("api-1:update_release", kwargs={"release_id": release.id})
    data = {
        "name": "v1.0.0",
        "description": "Test release",
        "is_prerelease": False,
        "created_at": new_created.isoformat(),
        "released_at": new_released.isoformat(),
    }

    response = client.put(
        url,
        data=json.dumps(data),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200

    # Verify the dates were updated
    release.refresh_from_db()
    assert release.released_at.date() == new_released.date()
    assert release.created_at.date() == new_created.date()
    assert original_released != release.released_at
    assert original_created != release.created_at


# =============================================================================
# RELEASE VERSION TESTS
# =============================================================================


@pytest.mark.django_db
def test_create_release_with_version(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test creating a release with a version string."""
    client = Client()
    url = reverse("api-1:create_release")

    payload = {
        "name": "January Release",
        "version": "v1.0.0",
        "product_id": str(sample_product.id),
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "January Release"
    assert data["version"] == "v1.0.0"

    # Verify release was created in database with version
    release = Release.objects.get(id=data["id"])
    assert release.version == "v1.0.0"


@pytest.mark.django_db
def test_create_release_duplicate_version(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that creating a release with duplicate version fails."""
    client = Client()
    url = reverse("api-1:create_release")

    # Create first release with version
    Release.objects.create(product=sample_product, name="First Release", version="v1.0.0")

    payload = {
        "name": "Second Release",
        "version": "v1.0.0",  # Same version
        "product_id": str(sample_product.id),
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.django_db
def test_list_releases_filter_by_version(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test filtering releases by version."""
    client = Client()

    # Create releases with different versions
    Release.objects.create(product=sample_product, name="Release 1", version="v1.0.0")
    Release.objects.create(product=sample_product, name="Release 2", version="v2.0.0")
    Release.objects.create(product=sample_product, name="Release 3", version="v3.0.0")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Filter by specific version
    url = reverse("api-1:list_all_releases")
    response = client.get(
        url,
        {"product_id": str(sample_product.id), "version": "v2.0.0"},
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["version"] == "v2.0.0"
    assert data["items"][0]["name"] == "Release 2"


@pytest.mark.django_db
def test_list_releases_filter_by_version_not_found(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test filtering releases by version returns empty when not found."""
    client = Client()

    # Create a release with a version
    Release.objects.create(product=sample_product, name="Release 1", version="v1.0.0")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Filter by non-existent version
    url = reverse("api-1:list_all_releases")
    response = client.get(
        url,
        {"product_id": str(sample_product.id), "version": "v9.9.9"},
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 0


@pytest.mark.django_db
def test_release_response_includes_version(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that release responses include the version field."""
    client = Client()

    # Create release with version
    release = Release.objects.create(product=sample_product, name="Test Release", version="v1.2.3")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Get single release
    url = reverse("api-1:get_release", kwargs={"release_id": release.id})
    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert data["version"] == "v1.2.3"


@pytest.mark.django_db
def test_legacy_release_version_is_none(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that releases without version return None in API response."""
    client = Client()

    # Create release without version (legacy behavior)
    release = Release.objects.create(product=sample_product, name="Legacy Release")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    url = reverse("api-1:get_release", kwargs={"release_id": release.id})
    response = client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert data["version"] is None


@pytest.mark.django_db
def test_update_release_version_via_put(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test updating a release version via PUT."""
    client = Client()

    # Create release without version
    release = Release.objects.create(product=sample_product, name="Test Release")
    assert release.version == ""

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Update with version via PUT
    url = reverse("api-1:update_release", kwargs={"release_id": release.id})
    response = client.put(
        url,
        json.dumps({"name": "Test Release", "version": "v2.0.0", "is_prerelease": False}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "v2.0.0"

    # Verify in database
    release.refresh_from_db()
    assert release.version == "v2.0.0"


@pytest.mark.django_db
def test_patch_release_version(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching a release version via PATCH."""
    client = Client()

    # Create release with initial version
    release = Release.objects.create(product=sample_product, name="Test Release", version="v1.0.0")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Patch only the version
    url = reverse("api-1:patch_release", kwargs={"release_id": release.id})
    response = client.patch(
        url,
        json.dumps({"version": "v1.1.0"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "v1.1.0"
    assert data["name"] == "Test Release"  # Name unchanged

    # Verify in database
    release.refresh_from_db()
    assert release.version == "v1.1.0"


@pytest.mark.django_db
def test_update_release_to_duplicate_version_fails(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that updating a release to a duplicate version fails."""
    client = Client()

    # Create two releases
    Release.objects.create(product=sample_product, name="Release 1", version="v1.0.0")
    release2 = Release.objects.create(product=sample_product, name="Release 2", version="v2.0.0")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Try to update release2 to have the same version as release1
    url = reverse("api-1:patch_release", kwargs={"release_id": release2.id})
    response = client.patch(
        url,
        json.dumps({"version": "v1.0.0"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 400
    assert "version" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_clear_release_version_via_put(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test clearing a release version by omitting it in PUT."""
    client = Client()

    # Create release with version
    release = Release.objects.create(product=sample_product, name="Test Release", version="v1.0.0")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # PUT without version should clear it
    url = reverse("api-1:update_release", kwargs={"release_id": release.id})
    response = client.put(
        url,
        json.dumps({"name": "Test Release", "is_prerelease": False}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["version"] is None  # Empty string returns as None in API

    # Verify in database
    release.refresh_from_db()
    assert release.version == ""
