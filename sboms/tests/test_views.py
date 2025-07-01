from __future__ import annotations

import os
from urllib.parse import quote

import pytest
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse
from pytest_mock.plugin import MockerFixture
from django.contrib.messages import get_messages

from billing.models import BillingPlan
from core.tests.fixtures import sample_user  # noqa: F401
from core.utils import number_to_random_token
from teams.models import Member, Team

from ..models import SBOM, Component, Product, Project
from .fixtures import (
    sample_component,  # noqa: F401
    sample_product,  # noqa: F401
    sample_project,  # noqa: F401
    sample_sbom,  # noqa: F401
)


def setup_test_session(client: Client, team: Team, user) -> None:
    """Set up session data for tests.

    Args:
        client: The test client
        team: The team to set up session data for
        user: The user to log in
    """
    # Ensure team has a valid key
    if not team.key or len(team.key) < 9:
        team.key = number_to_random_token(team.id)
        team.save()

    # Get the member's role
    member = Member.objects.filter(user=user, team=team).first()
    if not member:
        raise ValueError("User is not a member of the team")

    role = member.role

    # Log in the user
    client.force_login(user)

    # Set up session data with team ID for API compatibility
    session = client.session
    session["user_teams"] = {
        team.key: {
            "role": role,
            "name": team.name,
            "is_default_team": member.is_default_team,
            "team_id": team.id
        }
    }
    session["current_team"] = {
        "key": team.key,
        "role": role,
        "name": team.name,
        "is_default_team": member.is_default_team,
        "id": team.id  # Add team ID for API endpoints
    }
    session.save()


@pytest.mark.django_db
def test_dashboard_pages_only_accessible_when_logged_in(sample_team_with_owner_member):  # Changed fixture and name
    """Test that dashboard pages require authentication."""
    client = Client()
    team = sample_team_with_owner_member.team

    # Setup billing plan
    BillingPlan.objects.create(
        key="dashboard_test_plan",
        name="Dashboard Test Plan",
        max_components=10,
        max_products=10,
        max_projects=10
    )
    team.billing_plan = "dashboard_test_plan"
    team.key = number_to_random_token(team.id)
    team.save()

    uris = [
        reverse("sboms:products_dashboard"),
        reverse("sboms:projects_dashboard"),
        reverse("sboms:components_dashboard"),
    ]

    # Test unauthenticated access
    for uri in uris:
        response = client.get(uri)
        assert response.status_code == 302
        assert quote(response.request["PATH_INFO"]) == uri

    # Authenticate with team context
    client.force_login(team.members.first())
    session = client.session
    session["current_team"] = {
        "id": team.id,
        "role": "owner",
        "key": team.key
    }
    session.save()

    # Test authenticated access
    for uri in uris:
        response = client.get(uri)
        assert response.status_code == 200
        assert quote(response.request["PATH_INFO"]) == uri


@pytest.mark.django_db
def test_products_dashboard_renders_correctly(sample_team_with_owner_member):  # Changed fixture and name
    """Test that the products dashboard renders correctly."""
    client = Client()
    team = sample_team_with_owner_member.team

    # Set valid team key that encodes the team ID
    team.key = number_to_random_token(team.id)
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["current_team"] = {"id": team.id, "role": "owner", "key": team.key}
    session.save()

    response = client.get(reverse("sboms:products_dashboard"))
    assert response.status_code == 200

    # Check that the page contains the Add Product button for owners
    content = response.content.decode()
    assert "Add Product" in content
    assert 'data-bs-target="#addProductModal"' in content


# Removed: test_create_product - POST functionality moved to API tests


# Removed: test_delete_product - POST functionality moved to API tests


@pytest.mark.django_db
def test_projects_dashboard_renders_correctly(sample_team_with_owner_member):  # Changed name
    """Test that the projects dashboard renders correctly."""
    client = Client()
    team = sample_team_with_owner_member.team

    team.key = number_to_random_token(team.id)
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["current_team"] = {"id": team.id, "role": "owner", "key": team.key}
    session.save()

    response = client.get(reverse("sboms:projects_dashboard"))
    assert response.status_code == 200

    # Check that the page contains the Add Project button for owners
    content = response.content.decode()
    assert "Add Project" in content
    assert 'data-bs-target="#addProjectModal"' in content


# Removed: test_create_project - POST functionality moved to API tests


# Removed: test_delete_project - POST functionality moved to API tests


@pytest.mark.django_db
def test_components_dashboard_renders_correctly(sample_team_with_owner_member):  # Changed name
    """Test that the components dashboard renders correctly."""
    client = Client()
    team = sample_team_with_owner_member.team

    team.key = number_to_random_token(team.id)
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["current_team"] = {"id": team.id, "role": "owner", "key": team.key}
    session.save()

    response = client.get(reverse("sboms:components_dashboard"))
    assert response.status_code == 200

    # Check that the page contains the Add Component button for owners
    content = response.content.decode()
    assert "Add Component" in content
    assert 'data-bs-target="#addComponentModal"' in content


# Removed: test_create_component - POST functionality moved to API tests


# Removed: test_create_duplicate_component - POST functionality moved to API tests


# Removed: test_delete_component - POST functionality moved to API tests


@pytest.mark.django_db
def test_details_page_only_accessible_when_logged_in(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
):
    """Test that details pages require authentication."""
    client = Client()

    uris = [
        reverse("sboms:product_details", kwargs={"product_id": sample_product.id}),
        reverse("sboms:project_details", kwargs={"project_id": sample_project.id}),
        reverse("sboms:component_details", kwargs={"component_id": sample_component.id}),
        reverse("sboms:sbom_details", kwargs={"sbom_id": sample_sbom.id}),
    ]

    # Test unauthenticated access
    for uri in uris:
        response: HttpResponse = client.get(uri)
        assert response.status_code == 302
        assert quote(response.request["PATH_INFO"]) == uri

    # Set up session with team access
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test authenticated access
    for uri in uris:
        response: HttpResponse = client.get(uri)
        assert response.status_code == 200
        assert quote(response.request["PATH_INFO"]) == uri


@pytest.mark.django_db
def test_public_pages_accessibility(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
):
    sample_product.is_public = True
    sample_product.save()

    sample_project.is_public = True
    sample_project.save()

    sample_component.is_public = True
    sample_component.save()

    uris = [
        reverse("sboms:product_details_public", kwargs={"product_id": sample_product.id}),
        reverse("sboms:project_details_public", kwargs={"project_id": sample_project.id}),
        reverse("sboms:component_details_public", kwargs={"component_id": sample_component.id}),
        reverse("sboms:sbom_details_public", kwargs={"sbom_id": sample_sbom.id}),
    ]

    client = Client()

    for uri in uris:
        response: HttpResponse = client.get(uri)

        response.status_code == 200
        assert quote(response.request["PATH_INFO"]) == uri


@pytest.mark.django_db
def test_unknown_detail_pages_fail_gracefully(sample_user):  # noqa: F811
    uris = [
        reverse("sboms:product_details", kwargs={"product_id": -1}),
        reverse("sboms:project_details", kwargs={"project_id": -1}),
        reverse("sboms:component_details", kwargs={"component_id": -1}),
        reverse("sboms:sbom_details", kwargs={"sbom_id": -1}),
    ]

    client = Client()

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    for uri in uris:
        response: HttpResponse = client.get(uri)

        assert response.status_code == 404
        assert quote(response.request["PATH_INFO"]) == uri
        # The response should use our custom 404 template which includes the messages component
        assert "core/components/messages.html" in [t.name for t in response.templates]


@pytest.mark.django_db
def test_sbom_download(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    """Test SBOM download functionality."""
    mocker.patch("boto3.resource")
    mocked_s3_get_file_data = mocker.patch("core.object_store.S3Client.get_file_data")
    mocked_s3_get_file_data.return_value = b'{"name": "com.github.test/test", "a": 1}'

    client = Client()

    uri = reverse("sboms:sbom_download", kwargs={"sbom_id": sample_sbom.id})

    # Test unauthenticated access
    response: HttpResponse = client.get(uri)
    assert response.status_code == 403

    # Set up session with team access
    setup_test_session(client, sample_sbom.component.team, sample_sbom.component.team.members.first())

    # Test authenticated access
    response: HttpResponse = client.get(uri)
    assert response.status_code == 200
    assert response.content == b'{"name": "com.github.test/test", "a": 1}'


@pytest.mark.django_db
def test_public_sbom_download(sample_sbom: SBOM, mocker: MockerFixture):  # noqa: F811
    mocker.patch("boto3.resource")
    mocked_s3_get_file_data = mocker.patch("core.object_store.S3Client.get_file_data")
    mocked_s3_get_file_data.return_value = b'{"name": "com.github.test/test", "a": 1}'

    sample_sbom.component.is_public = True
    sample_sbom.component.save()

    client = Client()

    non_existent_sbom_download_uri = reverse("sboms:sbom_download", kwargs={"sbom_id": -2})
    response: HttpResponse = client.get(non_existent_sbom_download_uri)

    assert response.status_code == 404

    uri = reverse("sboms:sbom_download", kwargs={"sbom_id": sample_sbom.id})

    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    assert quote(response.request["PATH_INFO"]) == uri
    assert response.json()["name"] == "com.github.test/test"

    sample_sbom.component.is_public = False
    sample_sbom.component.save()

    response: HttpResponse = client.get(uri)

    assert response.status_code == 403


@pytest.mark.django_db
def test_transfer_component_to_team(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test transferring a component to another team."""
    client = Client()

    uri = reverse("sboms:transfer_component", kwargs={"component_id": sample_component.id})

    # Set up session with team access
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    # Test transferring component
    response: HttpResponse = client.post(uri, {"team_key": sample_team_with_owner_member.team.key})
    assert response.status_code == 302

    # Verify component was transferred
    sample_component.refresh_from_db()
    assert sample_component.team == sample_team_with_owner_member.team



@pytest.mark.django_db
def test_sbom_download_project_not_found(client):
    uri = reverse("sboms:sbom_download_project", kwargs={"project_id": "-1"})
    response = client.get(uri)
    assert response.status_code == 404


@pytest.mark.django_db
def test_sbom_download_project_private_unauthorized(client, sample_project):  # noqa: F811
    sample_project.is_public = False
    sample_project.save()

    uri = reverse("sboms:sbom_download_project", kwargs={"project_id": sample_project.id})
    response = client.get(uri)
    assert response.status_code == 403


@pytest.mark.django_db
def test_sbom_download_project_public_success(client, sample_project, mocker):  # noqa: F811
    sample_project.is_public = True
    sample_project.save()

    mock_zip_content = b"mock zip content"
    mock_get_package = mocker.patch("sboms.views.get_project_sbom_package")
    # Fix: Return a string path instead of a Path object with read_bytes
    mock_get_package.return_value = "/tmp/mock/path.zip"  # nosec B108

    # Mock open to avoid actual file operations
    mock_open = mocker.patch("builtins.open")
    mock_open.return_value.__enter__.return_value.read.return_value = mock_zip_content

    uri = reverse("sboms:sbom_download_project", kwargs={"project_id": sample_project.id})
    response = client.get(uri)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"] == f"attachment; filename={sample_project.name}.cdx.zip"


@pytest.mark.django_db
def test_sbom_download_project_private_authorized(
    client,
    sample_project,  # noqa: F811
    sample_user,  # noqa: F811
    mocker,
):
    sample_project.is_public = False
    sample_project.save()

    # Login and set session data
    client.force_login(sample_user)
    session = client.session
    session["current_team"] = {"role": "admin"}
    session.save()

    mock_zip_content = b"mock zip content"
    mock_get_package = mocker.patch("sboms.views.get_project_sbom_package")
    # Fix: Return a string path instead of a Path object with read_bytes
    mock_get_package.return_value = "/tmp/mock/path.zip"  # nosec B108

    # Mock open to avoid actual file operations
    mock_open = mocker.patch("builtins.open")
    mock_open.return_value.__enter__.return_value.read.return_value = mock_zip_content

    # Mock verify_item_access to return True for authorized access
    mocker.patch("sboms.views.verify_item_access", return_value=True)

    uri = reverse("sboms:sbom_download_project", kwargs={"project_id": sample_project.id})
    response = client.get(uri)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"] == f"attachment; filename={sample_project.name}.cdx.zip"


@pytest.mark.django_db
def test_component_details_json_serialization(
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    sample_user,  # noqa: F811
):
    """Test that component details views properly serialize SBOM objects for JSON output without errors.

    This test ensures that the JSON serialization fix for SBOM objects in component detail views
    works correctly, preventing the "Object of type SBOM is not JSON serializable" error.
    """
    # Associate the SBOM with the component
    sample_sbom.component = sample_component
    sample_sbom.save()

    client = Client()
    client.force_login(sample_user)

    # Set up session with team access
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    # Test private component details view
    private_uri = reverse("sboms:component_details", kwargs={"component_id": sample_component.id})
    response = client.get(private_uri)

    # Should render successfully without JSON serialization errors
    assert response.status_code == 200

    # Basic content check - component name should be present
    content = response.content.decode()
    assert sample_component.name in content

    # Make component public for public view test
    sample_component.is_public = True
    sample_component.save()

    # Test public component details view
    public_uri = reverse("sboms:component_details_public", kwargs={"component_id": sample_component.id})
    response = client.get(public_uri)

    # Should render successfully without JSON serialization errors
    assert response.status_code == 200

    # Basic content check - component name should be present
    content = response.content.decode()
    assert sample_component.name in content

    # The main test is that both views render without JSON serialization errors
    # If we get here with status 200, the JSON serialization fix is working


# Removed: TestDuplicateNames - POST functionality moved to API tests where duplicate validation is tested


# Removed: TestBillingPlanLimits - POST functionality moved to API tests where billing limits are tested


@pytest.mark.django_db
def test_sbom_download_product_not_found(client):
    """Test product download with non-existent product ID."""
    uri = reverse("sboms:sbom_download_product", kwargs={"product_id": "nonexistent"})
    response = client.get(uri)
    assert response.status_code == 404


@pytest.mark.django_db
def test_sbom_download_product_private_unauthorized(client, sample_product):  # noqa: F811
    """Test product download for private product without authorization."""
    sample_product.is_public = False
    sample_product.save()

    uri = reverse("sboms:sbom_download_product", kwargs={"product_id": sample_product.id})
    response = client.get(uri)
    assert response.status_code == 403


@pytest.mark.django_db
def test_sbom_download_product_public_success(client, sample_product, mocker):  # noqa: F811
    """Test successful product download for public product."""
    sample_product.is_public = True
    sample_product.save()

    mock_zip_content = b"mock product zip content"
    mock_get_package = mocker.patch("sboms.views.get_product_sbom_package")
    mock_get_package.return_value = "/tmp/mock/product_path.zip"  # nosec B108

    # Mock open similar to existing project tests
    mock_open = mocker.patch("builtins.open")
    mock_open.return_value.__enter__.return_value.read.return_value = mock_zip_content

    uri = reverse("sboms:sbom_download_product", kwargs={"product_id": sample_product.id})
    response = client.get(uri)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"] == f"attachment; filename={sample_product.name}.cdx.zip"


@pytest.mark.django_db
def test_sbom_download_product_private_authorized(
    client,
    sample_product,  # noqa: F811
    sample_user,  # noqa: F811
    mocker,
):
    """Test successful product download for private product with authorization."""
    sample_product.is_public = False
    sample_product.save()

    # Login and set session data
    client.force_login(sample_user)
    session = client.session
    session["current_team"] = {"role": "admin"}
    session.save()

    mock_zip_content = b"mock authorized product zip content"
    mock_get_package = mocker.patch("sboms.views.get_product_sbom_package")
    mock_get_package.return_value = "/tmp/mock/authorized_product_path.zip"  # nosec B108

    # Mock open similar to existing project tests
    mock_open = mocker.patch("builtins.open")
    mock_open.return_value.__enter__.return_value.read.return_value = mock_zip_content

    # Mock verify_item_access to return True for authorized access
    mocker.patch("sboms.views.verify_item_access", return_value=True)

    uri = reverse("sboms:sbom_download_product", kwargs={"product_id": sample_product.id})
    response = client.get(uri)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"] == f"attachment; filename={sample_product.name}.cdx.zip"



