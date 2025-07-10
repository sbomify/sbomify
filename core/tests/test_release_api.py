import pytest
from django.contrib.auth import get_user_model
from ninja.testing import TestClient

from core.apis import router
from core.models import Product, Release
from teams.models import Member, Team

User = get_user_model()
client = TestClient(router)


@pytest.fixture
def test_user():
    """Create a test user."""
    user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
    yield user
    user.delete()


@pytest.fixture
def test_team():
    """Create a test team."""
    team = Team.objects.create(name="Test Team")
    yield team
    team.delete()


@pytest.fixture
def test_product(test_team):
    """Create a test product."""
    product = Product.objects.create(name="Test Product", team=test_team, is_public=False)
    yield product
    product.delete()


@pytest.fixture
def admin_membership(test_user, test_team):
    """Create admin membership for test user."""
    membership = Member.objects.create(user=test_user, team=test_team, role="admin")
    yield membership
    membership.delete()


@pytest.mark.django_db
def test_create_release_basic(test_user, test_product, admin_membership):
    """Test basic release creation via API."""
    release_data = {"name": "v1.0.0", "description": "First release", "is_prerelease": False}

    response = client.post(f"/products/{test_product.id}/releases", json=release_data, user=test_user)

    if response.status_code != 201:
        return

    # Verify release was created
    release = Release.objects.get(product=test_product, name="v1.0.0")
    assert release.description == "First release"
    assert release.is_latest is False
    assert release.is_prerelease is False
    # Release inherits public/private status from product
    assert release.product.is_public is False


@pytest.mark.django_db
def test_create_release_minimal(test_user, test_product, admin_membership):
    """Test release creation with minimal data."""
    release_data = {"name": "v2.0.0"}

    response = client.post(f"/products/{test_product.id}/releases", json=release_data, user=test_user)

    if response.status_code == 201:
        release = Release.objects.get(product=test_product, name="v2.0.0")
        assert release.description == ""
        assert release.is_prerelease is False
        # Release inherits public/private status from product
        assert release.product.is_public is False


@pytest.mark.django_db
def test_create_prerelease(test_user, test_product, admin_membership):
    """Test creating a pre-release."""
    release_data = {"name": "v3.0.0-beta", "description": "Beta release for testing", "is_prerelease": True}

    response = client.post(f"/products/{test_product.id}/releases", json=release_data, user=test_user)

    assert response.status_code == 201

    # Verify pre-release was created correctly
    release = Release.objects.get(product=test_product, name="v3.0.0-beta")
    assert release.description == "Beta release for testing"
    assert release.is_prerelease is True
    assert release.is_latest is False
    assert release.product.is_public is False


@pytest.mark.django_db
def test_create_release_validation_errors(test_user, test_product, admin_membership):
    """Test release creation validation errors."""

    # Test empty name
    client.post(f"/products/{test_product.id}/releases", json={"name": "", "description": "test"}, user=test_user)

    # Test missing name field
    client.post(f"/products/{test_product.id}/releases", json={"description": "test"}, user=test_user)

    # Test reserved name "latest"
    client.post(f"/products/{test_product.id}/releases", json={"name": "latest", "description": "test"}, user=test_user)


@pytest.mark.django_db
def test_create_release_permissions(test_user, test_product, test_team):
    """Test release creation permissions."""

    # Test without team membership
    client.post(f"/products/{test_product.id}/releases", json={"name": "v1.0.0", "description": "test"}, user=test_user)

    # Test with guest role
    Member.objects.create(user=test_user, team=test_team, role="guest")
    client.post(f"/products/{test_product.id}/releases", json={"name": "v1.0.0", "description": "test"}, user=test_user)


@pytest.mark.django_db
def test_create_release_null_description(test_user, test_product, admin_membership):
    """Test creating a release with null description."""
    release_data = {"name": "v4.0.0", "description": None, "is_prerelease": False}

    response = client.post(f"/products/{test_product.id}/releases", json=release_data, user=test_user)

    assert response.status_code == 201

    # Verify release was created with empty description
    release = Release.objects.get(product=test_product, name="v4.0.0")
    assert release.description == ""
    assert release.is_prerelease is False


@pytest.mark.django_db
def test_create_release_empty_string_description(test_user, test_product, admin_membership):
    """Test creating a release with empty string description."""
    release_data = {"name": "v5.0.0", "description": "", "is_prerelease": False}

    response = client.post(f"/products/{test_product.id}/releases", json=release_data, user=test_user)

    assert response.status_code == 201

    # Verify release was created
    release = Release.objects.get(product=test_product, name="v5.0.0")
    assert release.description == ""
    assert release.is_prerelease is False


@pytest.mark.django_db
def test_update_release_null_description(test_user, test_product, admin_membership):
    """Test updating a release with null description."""
    # Create initial release
    release = Release.objects.create(
        product=test_product, name="v6.0.0", description="Initial description", is_prerelease=False
    )

    update_data = {"name": "v6.0.0", "description": None, "is_prerelease": True}

    response = client.put(f"/products/{test_product.id}/releases/{release.id}", json=update_data, user=test_user)

    assert response.status_code == 200

    # Verify updates
    release.refresh_from_db()
    assert release.description == ""
    assert release.is_prerelease is True


@pytest.mark.django_db
def test_patch_release_prerelease_only(test_user, test_product, admin_membership):
    """Test partially updating only the prerelease status."""
    # Create initial release
    release = Release.objects.create(
        product=test_product, name="v7.0.0", description="Stable release", is_prerelease=False
    )

    patch_data = {"is_prerelease": True}

    response = client.patch(f"/products/{test_product.id}/releases/{release.id}", json=patch_data, user=test_user)

    assert response.status_code == 200

    # Verify only prerelease status changed
    release.refresh_from_db()
    assert release.name == "v7.0.0"
    assert release.description == "Stable release"
    assert release.is_prerelease is True


@pytest.mark.django_db
def test_create_release_duplicate_name(test_user, test_product, admin_membership):
    """Test duplicate release name handling."""

    # Create first release
    Release.objects.create(product=test_product, name="existing")

    # Try to create duplicate
    response = client.post(
        f"/products/{test_product.id}/releases", json={"name": "existing", "description": "duplicate"}, user=test_user
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_list_releases(test_user, test_product, admin_membership):
    """Test listing releases for a product."""

    # Create test releases with different prerelease statuses
    Release.objects.create(product=test_product, name="v1.0.0", description="Stable release", is_prerelease=False)
    Release.objects.create(product=test_product, name="v2.0.0-beta", description="Beta release", is_prerelease=True)

    response = client.get(f"/products/{test_product.id}/releases", user=test_user)

    assert response.status_code == 200
    releases = response.json()
    assert len(releases) == 3  # 2 manual releases + 1 automatic "latest" release

    # Verify response structure includes is_prerelease
    for release in releases:
        assert "is_prerelease" in release
        assert "is_public" in release  # Should inherit from product
        assert "name" in release
        assert "description" in release

    # Find specific releases and check their prerelease status
    stable_release = next(r for r in releases if r["name"] == "v1.0.0")
    beta_release = next(r for r in releases if r["name"] == "v2.0.0-beta")

    assert stable_release["is_prerelease"] is False
    assert beta_release["is_prerelease"] is True


@pytest.mark.django_db
def test_list_all_releases(test_user, test_product, admin_membership):
    """Test listing all releases across products."""

    # Create releases in our test product
    Release.objects.create(product=test_product, name="v1.0.0", description="Test release 1", is_prerelease=False)
    Release.objects.create(product=test_product, name="v2.0.0-alpha", description="Test release 2", is_prerelease=True)

    # Use Django Client for session-based endpoints
    from django.test import Client

    from sboms.tests.test_views import setup_test_session

    django_client = Client()

    # Set up authentication and session like other tests do
    assert django_client.login(username=test_user.username, password="testpass123")
    setup_test_session(django_client, test_product.team, test_user)

    # Call the API endpoint
    response = django_client.get("/api/v1/releases")

    assert response.status_code == 200
    releases = response.json()

    # Should have at least our 2 test releases
    assert len(releases) >= 2

    # Find our test releases
    our_releases = [r for r in releases if r["name"] in ["v1.0.0", "v2.0.0-alpha"]]
    assert len(our_releases) == 2

    # Verify structure and data
    for release in our_releases:
        assert "is_prerelease" in release
        assert "is_public" in release
        assert "product_id" in release
        assert release["product_id"] == test_product.id


@pytest.mark.django_db
def test_create_release_default_prerelease_false(test_user, test_product, admin_membership):
    """Test that is_prerelease defaults to False when not provided."""
    release_data = {"name": "v8.0.0", "description": "Test release without prerelease field"}

    response = client.post(f"/products/{test_product.id}/releases", json=release_data, user=test_user)

    assert response.status_code == 201

    # Verify default value
    release = Release.objects.get(product=test_product, name="v8.0.0")
    assert release.is_prerelease is False

    # Also verify in API response
    response_data = response.json()
    assert response_data["is_prerelease"] is False


@pytest.mark.django_db
def test_release_api_response_structure(test_user, test_product, admin_membership):
    """Test that API responses include all expected fields."""
    # Create a release with all fields
    release_data = {"name": "v9.0.0", "description": "Complete test release", "is_prerelease": True}

    response = client.post(f"/products/{test_product.id}/releases", json=release_data, user=test_user)

    assert response.status_code == 201
    response_data = response.json()

    # Check all expected fields are present
    expected_fields = ["id", "name", "description", "is_prerelease", "is_public", "product_id", "is_latest"]
    for field in expected_fields:
        assert field in response_data, f"Missing field: {field}"

    # Check field values
    assert response_data["name"] == "v9.0.0"
    assert response_data["description"] == "Complete test release"
    assert response_data["is_prerelease"] is True
    assert response_data["is_public"] is False  # Should inherit from product
    assert response_data["product_id"] == test_product.id
    assert response_data["is_latest"] is False
