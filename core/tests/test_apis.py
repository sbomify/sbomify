"""Tests for core API endpoints."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from access_tokens.models import AccessToken
from core.tests.shared_fixtures import get_api_headers
from sboms.tests.fixtures import sample_access_token, sample_product  # noqa: F401
from teams.fixtures import sample_team_with_owner_member  # noqa: F401
from teams.models import Team, Member
from sboms.models import Product
from sboms.tests.test_views import setup_test_session

User = get_user_model()


@pytest.mark.django_db
def test_list_teams_api_authenticated(sample_access_token, sample_team):  # noqa: F811
    """Test listing teams via API with valid access token."""
    client = Client()

    response = client.get(
        reverse("api-1:list_teams"),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == sample_team.name


@pytest.mark.django_db
def test_list_teams_api_unauthenticated():
    """Test listing teams via API without authentication."""
    client = Client()

    response = client.get(reverse("api-1:list_teams"))

    assert response.status_code == 401


@pytest.mark.django_db
def test_get_team_api_authenticated(sample_access_token, sample_team):  # noqa: F811
    """Test getting specific team via API with valid access token."""
    client = Client()

    response = client.get(
        reverse("api-1:get_team", kwargs={"team_key": sample_team.key}),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == sample_team.name
    assert data["key"] == sample_team.key


@pytest.mark.django_db
def test_get_team_api_nonexistent(sample_access_token):  # noqa: F811
    """Test getting non-existent team via API."""
    client = Client()

    response = client.get(
        reverse("api-1:get_team", kwargs={"team_key": "nonexistent"}),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_update_team_api_authenticated(sample_access_token, sample_team):  # noqa: F811
    """Test updating team via API with valid access token."""
    client = Client()

    update_data = {"name": "Updated Team Name"}

    response = client.patch(
        reverse("api-1:update_team", kwargs={"team_key": sample_team.key}),
        json.dumps(update_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Team Name"

    # Verify the team was actually updated
    sample_team.refresh_from_db()
    assert sample_team.name == "Updated Team Name"


@pytest.mark.django_db
def test_api_requires_valid_token():
    """Test that API endpoints require valid access tokens."""
    client = Client()

    # Test with completely invalid token format
    invalid_headers = {"HTTP_AUTHORIZATION": "Bearer invalid-token-format"}

    response = client.get(reverse("api-1:list_teams"), **invalid_headers)
    assert response.status_code in [401, 403]

    # Test with malformed JWT token
    malformed_headers = {"HTTP_AUTHORIZATION": "Bearer not.a.valid.jwt"}

    response = client.get(reverse("api-1:list_teams"), **malformed_headers)
    assert response.status_code in [401, 403]


@pytest.mark.django_db
def test_api_endpoints_with_malformed_token():
    """Test API endpoints with malformed authorization headers."""
    client = Client()

    # Test with malformed header
    malformed_headers = {"HTTP_AUTHORIZATION": "Bearer invalid-token-format"}

    response = client.get(reverse("api-1:list_teams"), **malformed_headers)
    assert response.status_code in [401, 403]

    # Test with missing Bearer prefix
    malformed_headers = {"HTTP_AUTHORIZATION": "invalid-token-format"}

    response = client.get(reverse("api-1:list_teams"), **malformed_headers)
    assert response.status_code in [401, 403]


@pytest.mark.django_db
def test_api_endpoints_require_team_membership(sample_access_token):  # noqa: F811
    """Test that API endpoints require appropriate team membership."""
    client = Client()

    # Create a team that the user is not a member of
    from teams.models import Team

    other_team = Team.objects.create(name="Other Team")

    response = client.get(
        reverse("api-1:get_team", kwargs={"team_key": other_team.key}),
        **get_api_headers(sample_access_token),
    )

    # Should return 403/404 for teams user is not a member of
    assert response.status_code in [403, 404]


@pytest.mark.django_db
def test_api_pagination_products(sample_access_token, sample_team):  # noqa: F811
    """Test that products API endpoint supports pagination."""
    from core.models import Product

    client = Client()

    # Create multiple products to test pagination
    products = []
    for i in range(25):
        product = Product.objects.create(name=f"Test Product {i+1}", team=sample_team)
        products.append(product)

    # Test first page with default page size
    response = client.get(
        reverse("api-1:list_products"),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()

    # Check paginated response structure
    assert "items" in data
    assert "pagination" in data

    pagination = data["pagination"]
    assert "total" in pagination
    assert "page" in pagination
    assert "page_size" in pagination
    assert "total_pages" in pagination
    assert "has_previous" in pagination
    assert "has_next" in pagination

    assert pagination["total"] == 25
    assert pagination["page"] == 1
    assert pagination["page_size"] == 15
    assert pagination["total_pages"] == 2
    assert pagination["has_previous"] is False
    assert pagination["has_next"] is True
    assert len(data["items"]) == 15

    # Test second page
    response = client.get(
        reverse("api-1:list_products") + "?page=2",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()

    pagination = data["pagination"]
    assert pagination["page"] == 2
    assert pagination["has_previous"] is True
    assert pagination["has_next"] is False
    assert len(data["items"]) == 10  # Remaining items on last page

    # Test custom page size
    response = client.get(
        reverse("api-1:list_products") + "?page=1&page_size=10",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()

    pagination = data["pagination"]
    assert pagination["page_size"] == 10
    assert pagination["total_pages"] == 3
    assert len(data["items"]) == 10


@pytest.mark.django_db
def test_api_pagination_projects(sample_access_token, sample_team):  # noqa: F811
    """Test that projects API endpoint supports pagination."""
    from core.models import Project

    client = Client()

    # Create multiple projects to test pagination
    for i in range(30):
        Project.objects.create(name=f"Test Project {i+1}", team=sample_team)

    # Test first page
    response = client.get(
        reverse("api-1:list_projects"),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    assert "pagination" in data
    assert data["pagination"]["total"] == 30
    assert len(data["items"]) == 15  # Default page size


@pytest.mark.django_db
def test_api_pagination_components(sample_access_token, sample_team):  # noqa: F811
    """Test that components API endpoint supports pagination."""
    from core.models import Component

    client = Client()

    # Create multiple components to test pagination
    for i in range(20):
        Component.objects.create(name=f"Test Component {i+1}", component_type="sbom", team=sample_team)

    # Test first page
    response = client.get(
        reverse("api-1:list_components"),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    assert "pagination" in data
    assert data["pagination"]["total"] == 20
    assert len(data["items"]) == 15  # Default page size


@pytest.mark.django_db
def test_api_pagination_invalid_params(sample_access_token, sample_team):  # noqa: F811
    """Test pagination with invalid parameters."""
    from core.models import Product

    client = Client()

    # Create a few products
    for i in range(5):
        Product.objects.create(name=f"Test Product {i+1}", team=sample_team)

    # Test with invalid page number (should default to page 1)
    response = client.get(
        reverse("api-1:list_products") + "?page=999",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["page"] == 1

    # Test with invalid page size (should be clamped to valid range)
    response = client.get(
        reverse("api-1:list_products") + "?page_size=999",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["page_size"] == 100  # Max allowed

    # Test with zero page size (should default to 1)
    response = client.get(
        reverse("api-1:list_products") + "?page_size=0",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"]["page_size"] == 1  # Min allowed


@pytest.mark.django_db
def test_api_cors_headers(sample_access_token, sample_team):  # noqa: F811
    """Test that API responses include appropriate CORS headers."""
    client = Client()

    response = client.get(
        reverse("api-1:list_teams"),
        **get_api_headers(sample_access_token),
    )

    # Check for standard API response headers
    assert response.status_code == 200
    assert "Content-Type" in response
    assert response["Content-Type"] == "application/json; charset=utf-8"


@pytest.mark.django_db
def test_api_error_handling(sample_access_token):  # noqa: F811
    """Test API error handling and response format."""
    client = Client()

    # Test 404 error response format
    response = client.get(
        reverse("api-1:get_team", kwargs={"team_key": "nonexistent"}),
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)


# =============================================================================
# PRODUCT DOWNLOAD TESTS
# =============================================================================


@pytest.mark.django_db
def test_download_private_product_sbom_success(
    client,
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member,  # noqa: F811
    tmp_path,
    mocker,
):
    """Test downloading private product SBOM with proper authorization."""
    # Make product private
    sample_product.is_public = False
    sample_product.save()

    # Create a mock SBOM file
    mock_package = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "timestamp": "2024-01-01T00:00:00Z",
            "component": {"type": "application", "name": sample_product.name},
        },
        "components": [],
    }

    # Create a mock file that will be returned by the mock function
    mock_file_path = tmp_path / f"{sample_product.name}.cdx.json"
    mock_file_path.write_text(json.dumps(mock_package, indent=2))

    # Mock the SBOM package generator to return the file path
    mock_get_product_sbom_package = mocker.patch("core.apis.get_product_sbom_package")
    mock_get_product_sbom_package.return_value = mock_file_path

    # Set up authentication and session
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    url = reverse("api-1:download_product_sbom", kwargs={"product_id": sample_product.id})
    response = client.get(url)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert f"attachment; filename={sample_product.name}.cdx.json" in response["Content-Disposition"]

    # Verify the mock was called with correct parameters
    mock_get_product_sbom_package.assert_called_once()
    call_args = mock_get_product_sbom_package.call_args
    assert call_args[0][0] == sample_product  # First argument should be the product

    # Verify response content
    data = response.json()
    assert data["bomFormat"] == "CycloneDX"
    assert data["metadata"]["component"]["name"] == sample_product.name


@pytest.mark.django_db
def test_download_private_product_sbom_unauthorized(
    client,
    sample_product: Product,  # noqa: F811
):
    """Test downloading private product SBOM without authorization fails."""
    # Make product private
    sample_product.is_public = False
    sample_product.save()

    url = reverse("api-1:download_product_sbom", kwargs={"product_id": sample_product.id})
    response = client.get(url)

    assert response.status_code == 403
    assert "Authentication required" in response.json()["detail"]


@pytest.mark.django_db
def test_download_private_product_sbom_wrong_team(
    client,
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member,  # noqa: F811
):
    """Test downloading private product SBOM with wrong team access fails."""
    # Make product private
    sample_product.is_public = False
    sample_product.save()

    # Create different team
    other_team = Team.objects.create(name="other-team", key="other-team")
    other_user = User.objects.create_user(username="other-user", password="password")
    Member.objects.create(user=other_user, team=other_team, role="owner")

    # Set up authentication with wrong team
    setup_test_session(client, other_team, other_user)

    url = reverse("api-1:download_product_sbom", kwargs={"product_id": sample_product.id})
    response = client.get(url)

    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


@pytest.mark.django_db
def test_download_product_sbom_schema_error(
    client,
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member,  # noqa: F811
    mocker,
):
    """Test that schema content errors are properly handled in product SBOM download."""
    # Make product private
    sample_product.is_public = False
    sample_product.save()

    # Mock the SBOM package generator to raise the schema error we had
    mock_get_product_sbom_package = mocker.patch("core.apis.get_product_sbom_package")
    mock_get_product_sbom_package.side_effect = AttributeError("type object 'Type3' has no attribute 'releaseNotes'")

    # Set up authentication and session
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    url = reverse("api-1:download_product_sbom", kwargs={"product_id": sample_product.id})
    response = client.get(url)

    assert response.status_code == 500
    assert "Error generating product SBOM" in response.json()["detail"]
    assert "Type3" in response.json()["detail"]


@pytest.mark.django_db
def test_download_product_sbom_with_documents(
    client,
    sample_product: Product,  # noqa: F811
    sample_team_with_owner_member,  # noqa: F811
    tmp_path,
    mocker,
):
    """Test that documents are included in product SBOM external references."""
    # Make product private
    sample_product.is_public = False
    sample_product.save()

    # Create a document component
    from core.models import Component
    from documents.models import Document

    doc_component = Component.objects.create(
        name="Test Document Component", team=sample_product.team, component_type="document", is_public=True
    )

    document = Document.objects.create(
        name="Test Document",
        component=doc_component,
        document_type="specification",
        description="Test specification document",
    )

    # Create a mock SBOM file with external references
    mock_package = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "timestamp": "2024-01-01T00:00:00Z",
            "component": {
                "type": "application",
                "name": sample_product.name,
                "externalReferences": [
                    {
                        "type": "documentation",
                        "url": f"http://testserver{document.get_external_reference_url()}",
                        "comment": "Test specification document",
                    }
                ],
            },
        },
        "components": [],
    }

    # Create a mock file that will be returned by the mock function
    mock_file_path = tmp_path / f"{sample_product.name}.cdx.json"
    mock_file_path.write_text(json.dumps(mock_package, indent=2))

    # Mock the SBOM package generator to return the file path
    mock_get_product_sbom_package = mocker.patch("core.apis.get_product_sbom_package")
    mock_get_product_sbom_package.return_value = mock_file_path

    # Set up authentication and session
    setup_test_session(client, sample_product.team, sample_team_with_owner_member.user)

    url = reverse("api-1:download_product_sbom", kwargs={"product_id": sample_product.id})
    response = client.get(url)

    assert response.status_code == 200
    data = response.json()

    # Verify documents are included in external references
    external_refs = data["metadata"]["component"]["externalReferences"]
    assert len(external_refs) > 0

    # Find the document reference
    doc_ref = next((ref for ref in external_refs if ref["type"] == "documentation"), None)
    assert doc_ref is not None
    assert document.name in doc_ref["url"] or "document" in doc_ref["url"]
    assert doc_ref["comment"] == "Test specification document"
