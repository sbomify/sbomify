import json

import pytest
from django.test import Client
from ninja.testing import TestClient

from core.apis import router
from core.models import Release
from core.tests.fixtures import guest_user, sample_user  # noqa: F401
from sboms.tests.fixtures import (  # noqa: F401
    sample_access_token,
    sample_component,
    sample_product,
    sample_project,
)
from teams.fixtures import sample_team  # noqa: F401
from teams.models import Member

client = TestClient(router)


@pytest.mark.django_db
def test_create_release_success(sample_user, sample_product, sample_access_token):  # noqa: F811
    """Test successful release creation via API."""
    # sample_product fixture already creates team membership through sample_team_with_owner_member
    django_client = Client()

    # Test data
    release_data = {
        "name": "v1.0.0",
        "description": "First release",
        "is_public": False
    }

    url = f"/api/v1/products/{sample_product.id}/releases"

    # Make the API call using Django Client with proper authentication
    response = django_client.post(
        url,
        json.dumps(release_data),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 201

    # Verify release was created
    release = Release.objects.get(product=sample_product, name="v1.0.0")
    assert release.description == "First release"
    assert release.product.is_public is False  # is_public is inherited from product
    assert release.is_latest is False


@pytest.mark.django_db
def test_create_release_validation_errors(sample_user, sample_product, sample_access_token):  # noqa: F811
    """Test release creation with various validation errors."""
    # sample_product fixture already creates team membership through sample_team_with_owner_member
    django_client = Client()
    url = f"/api/v1/products/{sample_product.id}/releases"

    # Test empty name
    response = django_client.post(
        url,
        json.dumps({"name": "", "description": "test"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code in [400, 422]  # Validation error

    # Test missing name
    response = django_client.post(
        url,
        json.dumps({"description": "test"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code in [400, 422]  # Validation error

    # Test reserved name "latest"
    response = django_client.post(
        url,
        json.dumps({"name": "latest", "description": "test"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 400  # Should reject "latest" name

    # Test duplicate name
    Release.objects.create(product=sample_product, name="existing")
    response = django_client.post(
        url,
        json.dumps({"name": "existing", "description": "test"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 400  # Duplicate name error


@pytest.mark.django_db
def test_create_release_permission_errors(sample_user, sample_product, guest_user, sample_access_token):  # noqa: F811
    """Test release creation with permission errors."""
    django_client = Client()

    # Test without team membership - using a user with access token but no team membership
    # Create an access token for guest_user
    from access_tokens.utils import create_personal_access_token
    guest_token_str = create_personal_access_token(guest_user)

    url = f"/api/v1/products/{sample_product.id}/releases"
    payload = {"name": "v1.0.0", "description": "test"}

    response = django_client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {guest_token_str}",
    )
    assert response.status_code == 403

    # Test with guest role (insufficient permissions)
    team = sample_product.team
    Member.objects.create(user=guest_user, team=team, role="guest")
    response = django_client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {guest_token_str}",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_create_release_schema_validation(sample_user, sample_product, sample_access_token):  # noqa: F811
    """Test release creation with various data types and schema validation."""
    # sample_product fixture already creates team membership through sample_team_with_owner_member
    django_client = Client()
    url = f"/api/v1/products/{sample_product.id}/releases"

    # Test with all valid fields
    response = django_client.post(
        url,
        json.dumps({
            "name": "v2.0.0",
            "description": "Test release with all fields",
            "is_prerelease": True  # Fixed: should be is_prerelease, not is_public
        }),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 201

    # Test with minimal fields
    response = django_client.post(
        url,
        json.dumps({"name": "v3.0.0"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 201

    # Test with extra unexpected fields
    response = django_client.post(
        url,
        json.dumps({
            "name": "v4.0.0",
            "description": "test",
            "is_prerelease": False,
            "unexpected_field": "should be ignored"
        }),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 201  # Should succeed despite extra field


@pytest.mark.django_db
def test_list_releases(sample_user, sample_product, sample_access_token):  # noqa: F811
    """Test listing releases for a product."""
    # sample_product fixture already creates team membership through sample_team_with_owner_member
    django_client = Client()

    # Create some test releases
    Release.objects.create(product=sample_product, name="v1.0.0", description="First")
    Release.objects.create(product=sample_product, name="v2.0.0", description="Second")

    # Test listing releases
    url = f"/api/v1/products/{sample_product.id}/releases"
    response = django_client.get(
        url,
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2



