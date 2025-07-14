"""Tests for SBOM CRUD API endpoints (Product, Project, Component)."""

from __future__ import annotations

import json
import os

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from access_tokens.models import AccessToken
from billing.models import BillingPlan
from core.models import Component, Product, Project, User
from core.tests.shared_fixtures import get_api_headers
from sboms.models import ProductIdentifier
from core.tests.fixtures import sample_user  # noqa: F401
from sboms.tests.fixtures import (  # noqa: F401
    sample_access_token,
    sample_billing_plan,
    sample_component,
    sample_product,
    sample_project,
)
from sboms.tests.test_views import setup_test_session
from teams.fixtures import sample_team_with_owner_member, sample_team_with_guest_member  # noqa: F401
from teams.models import Member
from sboms.models import ProductLink

# =============================================================================
# PRODUCT CRUD TESTS
# =============================================================================


@pytest.mark.django_db
def test_create_product_success(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """Test successful product creation."""
    client = Client()
    url = reverse("api-1:create_product")

    # Set up billing plan for the team
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()

    payload = {"name": "Test Product"}

    # Set up authentication
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    # Set up session with team
    setup_test_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Product"
    assert data["team_id"] == str(sample_team_with_owner_member.team.id)
    assert data["is_public"] is False
    assert "id" in data
    assert "created_at" in data
    assert "project_count" in data

    # Verify product was created in database
    product = Product.objects.get(id=data["id"])
    assert product.name == "Test Product"
    assert product.team_id == sample_team_with_owner_member.team.id


@pytest.mark.django_db
def test_create_product_duplicate_name(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test product creation with duplicate name fails."""
    client = Client()
    url = reverse("api-1:create_product")

    payload = {"name": sample_product.name}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.django_db
def test_list_products(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test listing products for a team."""
    client = Client()
    url = reverse("api-1:list_products")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == sample_product.id
    assert data["items"][0]["name"] == sample_product.name


@pytest.mark.django_db
def test_get_product_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test getting a specific product."""
    client = Client()
    url = reverse("api-1:get_product", kwargs={"product_id": sample_product.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == sample_product.id
    assert data["name"] == sample_product.name
    assert data["team_id"] == str(sample_product.team_id)


@pytest.mark.django_db
def test_get_product_not_found(
    sample_access_token: AccessToken,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test getting non-existent product returns 404."""
    client = Client()
    url = reverse("api-1:get_product", kwargs={"product_id": "nonexistent"})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_update_product_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful product update."""
    client = Client()
    url = reverse("api-1:update_product", kwargs={"product_id": sample_product.id})

    payload = {"name": "Updated Product", "is_public": True}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Product"
    assert data["is_public"] is True

    # Verify update in database
    sample_product.refresh_from_db()
    assert sample_product.name == "Updated Product"
    assert sample_product.is_public is True


@pytest.mark.django_db
def test_delete_product_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful product deletion."""
    client = Client()
    url = reverse("api-1:delete_product", kwargs={"product_id": sample_product.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.delete(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Verify deletion in database
    assert not Product.objects.filter(id=sample_product.id).exists()


@pytest.mark.django_db
def test_link_projects_to_product(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test linking projects to a product via PATCH operation."""
    client = Client()
    url = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})

    # Ensure project is in same team
    sample_project.team = sample_product.team
    sample_project.save()

    payload = {"project_ids": [sample_project.id]}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200

    # Verify link in database
    assert sample_product.projects.filter(id=sample_project.id).exists()


@pytest.mark.django_db
def test_unlink_projects_from_product(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test unlinking projects from a product via PATCH operation."""
    client = Client()

    # Ensure project is in same team and linked to product
    sample_project.team = sample_product.team
    sample_project.save()
    sample_product.projects.add(sample_project)

    url = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})
    payload = {"project_ids": []}  # Empty array to remove all projects

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200

    # Verify unlink in database
    assert not sample_product.projects.filter(id=sample_project.id).exists()


# =============================================================================
# PROJECT CRUD TESTS
# =============================================================================


@pytest.mark.django_db
def test_create_project_success(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """Test successful project creation."""
    client = Client()
    url = reverse("api-1:create_project")

    # Set up billing plan for the team
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()

    payload = {"name": "Test Project", "metadata": {"version": "1.0.0"}}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Project"
    assert data["team_id"] == str(sample_team_with_owner_member.team.id)
    assert data["metadata"] == {"version": "1.0.0"}
    assert "id" in data
    assert "created_at" in data
    assert "component_count" in data


@pytest.mark.django_db
def test_list_projects(
    sample_project: Project,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test listing projects for a team."""
    client = Client()
    url = reverse("api-1:list_projects")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == sample_project.id


@pytest.mark.django_db
def test_get_project_success(
    sample_project: Project,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test getting a specific project."""
    client = Client()
    url = reverse("api-1:get_project", kwargs={"project_id": sample_project.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == sample_project.id
    assert data["name"] == sample_project.name


@pytest.mark.django_db
def test_update_project_success(
    sample_project: Project,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful project update."""
    client = Client()
    url = reverse("api-1:update_project", kwargs={"project_id": sample_project.id})

    payload = {
        "name": "Updated Project",
        "is_public": True,
        "metadata": {"version": "2.0.0", "description": "Updated project"},
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Project"
    assert data["is_public"] is True
    assert data["metadata"]["version"] == "2.0.0"


@pytest.mark.django_db
def test_delete_project_success(
    sample_project: Project,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful project deletion."""
    client = Client()
    url = reverse("api-1:delete_project", kwargs={"project_id": sample_project.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    response = client.delete(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Verify deletion in database
    assert not Project.objects.filter(id=sample_project.id).exists()


@pytest.mark.django_db
def test_link_components_to_project(
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test linking components to a project via PATCH operation."""
    client = Client()
    url = reverse("api-1:patch_project", kwargs={"project_id": sample_project.id})

    # Ensure component is in same team
    sample_component.team = sample_project.team
    sample_component.save()

    payload = {"component_ids": [sample_component.id]}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200

    # Verify link in database
    assert sample_project.components.filter(id=sample_component.id).exists()


@pytest.mark.django_db
def test_unlink_components_from_project(
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test unlinking components from a project via PATCH operation."""
    client = Client()

    # Ensure component is in same team and linked to project
    sample_component.team = sample_project.team
    sample_component.save()
    sample_project.components.add(sample_component)

    url = reverse("api-1:patch_project", kwargs={"project_id": sample_project.id})
    payload = {"component_ids": []}  # Empty array to remove all components

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200

    # Verify unlink in database
    assert not sample_project.components.filter(id=sample_component.id).exists()


# =============================================================================
# COMPONENT CRUD TESTS
# =============================================================================


@pytest.mark.django_db
def test_create_component_success(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """Test successful component creation."""
    client = Client()
    url = reverse("api-1:create_component")

    # Set up billing plan for the team
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()

    payload = {"name": "Test Component", "metadata": {"version": "1.0.0"}}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Component"
    assert data["team_id"] == str(sample_team_with_owner_member.team.id)
    assert data["metadata"] == {"version": "1.0.0"}
    assert "sbom_count" in data


@pytest.mark.django_db
def test_list_components(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test listing components for a team."""
    client = Client()
    url = reverse("api-1:list_components")

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == sample_component.id


@pytest.mark.django_db
def test_get_component_success(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test getting a specific component."""
    client = Client()
    url = reverse("api-1:get_component", kwargs={"component_id": sample_component.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == sample_component.id
    assert data["name"] == sample_component.name


@pytest.mark.django_db
def test_update_component_success(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful component update."""
    client = Client()
    url = reverse("api-1:update_component", kwargs={"component_id": sample_component.id})

    payload = {
        "name": "Updated Component",
        "is_public": True,
        "metadata": {"version": "2.0.0", "description": "Updated component"},
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Component"
    assert data["is_public"] is True
    assert data["metadata"]["version"] == "2.0.0"


@pytest.mark.django_db
def test_delete_component_success(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test successful component deletion."""
    # Mock S3 operations
    mocker.patch("boto3.resource")
    mocker.patch("core.object_store.S3Client.delete_object")

    client = Client()
    url = reverse("api-1:delete_component", kwargs={"component_id": sample_component.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    response = client.delete(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Verify deletion in database
    assert not Component.objects.filter(id=sample_component.id).exists()


# =============================================================================
# AUTHORIZATION TESTS
# =============================================================================


@pytest.mark.django_db
def test_crud_operations_require_authentication():
    """Test that create operations require authentication, but list operations allow public access."""
    client = Client()

    # Create operations should require authentication
    create_urls = [
        reverse("api-1:create_product"),
        reverse("api-1:create_project"),
        reverse("api-1:create_component"),
    ]

    for url in create_urls:
        response = client.post(url, json.dumps({"name": "test"}), content_type="application/json")
        assert response.status_code in [401, 403]  # Unauthorized or Forbidden

    # List operations should allow public access (return 200 with empty items for no public items)
    list_urls = [
        reverse("api-1:list_products"),
        reverse("api-1:list_projects"),
        reverse("api-1:list_components"),
    ]

    for url in list_urls:
        response = client.get(url)
        assert response.status_code == 200  # Public access allowed
        data = response.json()
        assert "items" in data
        assert "pagination" in data


@pytest.mark.django_db
def test_crud_operations_require_billing_plan(
    sample_access_token: AccessToken,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that CRUD operations require an active billing plan when using access tokens."""
    client = Client()

    # Set up authentication but no team session - API will fall back to user's first team
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    # Explicitly clear any team session data that might have been set up
    session = client.session
    session.pop("current_team", None)
    session.pop("user_teams", None)
    session.save()

    create_urls = [
        reverse("api-1:create_product"),
        reverse("api-1:create_project"),
        reverse("api-1:create_component"),
    ]

    payload = {"name": "Test Item"}

    # Test create operations - these require billing plan validation
    for url in create_urls:
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 403
        assert "No active billing plan" in response.json()["detail"]


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


@pytest.mark.django_db
def test_create_product_missing_required_fields(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test product creation with missing required fields."""
    client = Client()
    url = reverse("api-1:create_product")

    payload = {}  # Missing name

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 422  # Validation error


@pytest.mark.django_db
def test_update_nonexistent_item(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test updating non-existent items returns 404."""
    client = Client()

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    payload = {"name": "Updated Name", "is_public": False}

    urls = [
        reverse("api-1:update_product", kwargs={"product_id": "nonexistent"}),
        reverse("api-1:update_project", kwargs={"project_id": "nonexistent"}),
        reverse("api-1:update_component", kwargs={"component_id": "nonexistent"}),
    ]

    for url in urls:
        response = client.put(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 404


# =============================================================================
# PATCH ENDPOINT TESTS
# =============================================================================


@pytest.mark.django_db
def test_patch_product_partial_update(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching product with partial data."""
    client = Client()
    url = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})

    payload = {"name": "Patched Product"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Patched Product"
    # Original is_public should remain unchanged
    assert data["is_public"] == sample_product.is_public


@pytest.mark.django_db
def test_patch_product_public_status_only(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching product with only public status."""
    client = Client()
    url = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})

    payload = {"is_public": True}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_public"] is True
    # Original name should remain unchanged
    assert data["name"] == sample_product.name


@pytest.mark.django_db
def test_patch_product_empty_body(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching product with empty body."""
    client = Client()
    url = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})

    payload = {}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    # Nothing should change
    assert data["name"] == sample_product.name
    assert data["is_public"] == sample_product.is_public


@pytest.mark.django_db
def test_patch_project_partial_update(
    sample_project: Project,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching project with partial data."""
    client = Client()
    url = reverse("api-1:patch_project", kwargs={"project_id": sample_project.id})

    payload = {"name": "Patched Project", "metadata": {"patch": True}}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Patched Project"
    assert data["metadata"]["patch"] is True
    # Original is_public should remain unchanged
    assert data["is_public"] == sample_project.is_public


@pytest.mark.django_db
def test_patch_project_metadata_only(
    sample_project: Project,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching project with only metadata."""
    client = Client()
    url = reverse("api-1:patch_project", kwargs={"project_id": sample_project.id})

    payload = {"metadata": {"new_field": "new_value"}}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["new_field"] == "new_value"
    # Original name and is_public should remain unchanged
    assert data["name"] == sample_project.name
    assert data["is_public"] == sample_project.is_public


@pytest.mark.django_db
def test_patch_component_partial_update(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching component with partial data."""
    client = Client()
    url = reverse("api-1:patch_component", kwargs={"component_id": sample_component.id})

    payload = {"is_public": True, "metadata": {"patched": True}}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_public"] is True
    assert data["metadata"]["patched"] is True
    # Original name should remain unchanged
    assert data["name"] == sample_component.name


@pytest.mark.django_db
def test_patch_component_name_only(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching component with only name."""
    client = Client()
    url = reverse("api-1:patch_component", kwargs={"component_id": sample_component.id})

    payload = {"name": "Patched Component"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Patched Component"
    # Original fields should remain unchanged
    assert data["is_public"] == sample_component.is_public
    assert data["metadata"] == sample_component.metadata


@pytest.mark.django_db
def test_patch_not_found(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching non-existent entities."""
    client = Client()

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

    urls = [
        reverse("api-1:patch_product", kwargs={"product_id": "nonexistent"}),
        reverse("api-1:patch_project", kwargs={"project_id": "nonexistent"}),
        reverse("api-1:patch_component", kwargs={"component_id": "nonexistent"}),
    ]

    for url in urls:
        response = client.patch(
            url,
            json.dumps({"name": "Test"}),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 404


@pytest.mark.django_db
def test_patch_unauthorized(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test patching without proper authentication."""
    client = Client()
    # No authentication/session setup

    urls = [
        reverse("api-1:patch_product", kwargs={"product_id": sample_product.id}),
        reverse("api-1:patch_project", kwargs={"project_id": sample_project.id}),
        reverse("api-1:patch_component", kwargs={"component_id": sample_component.id}),
    ]

    for url in urls:
        response = client.patch(
            url,
            json.dumps({"name": "Test"}),
            content_type="application/json",
        )
        assert response.status_code == 401


@pytest.mark.django_db
def test_patch_validation_errors(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching with invalid data."""
    client = Client()
    url = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test empty name
    payload = {"name": ""}
    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.django_db
def test_patch_component_empty_body(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test patching component with empty body should not change anything."""
    client = Client()
    url = reverse("api-1:patch_component", kwargs={"component_id": sample_component.id})

    payload = {}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    response = client.patch(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    # Nothing should change
    assert data["name"] == sample_component.name
    assert data["is_public"] == sample_component.is_public
    assert data["metadata"] == sample_component.metadata


# =============================================================================
# BUSINESS LOGIC TESTS (Moved from View Tests)
# =============================================================================

@pytest.mark.django_db
class TestDeleteOperationsAPI:
    """Test delete operations via API (migrated from view tests)."""

    def test_delete_product_api(
        self,
        sample_product: Product,
        sample_access_token: AccessToken,
    ):
        """Test product deletion via API."""
        client = Client()

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, sample_product.team, sample_product.team.members.first())

        url = reverse("api-1:delete_product", kwargs={"product_id": sample_product.id})
        response = client.delete(
            url,
            **get_api_headers(sample_access_token),
        )

        assert response.status_code == 204

        # Verify product was deleted from database
        assert not Product.objects.filter(id=sample_product.id).exists()

    def test_delete_project_api(
        self,
        sample_project: Project,
        sample_access_token: AccessToken,
    ):
        """Test project deletion via API."""
        client = Client()

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, sample_project.team, sample_project.team.members.first())

        url = reverse("api-1:delete_project", kwargs={"project_id": sample_project.id})
        response = client.delete(
            url,
            **get_api_headers(sample_access_token),
        )

        assert response.status_code == 204

        # Verify project was deleted from database
        assert not Project.objects.filter(id=sample_project.id).exists()

    def test_delete_component_api(
        self,
        sample_component: Component,
        sample_access_token: AccessToken,
    ):
        """Test component deletion via API."""
        client = Client()

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, sample_component.team, sample_component.team.members.first())

        url = reverse("api-1:delete_component", kwargs={"component_id": sample_component.id})
        response = client.delete(
            url,
            **get_api_headers(sample_access_token),
        )

        assert response.status_code == 204

        # Verify component was deleted from database
        assert not Component.objects.filter(id=sample_component.id).exists()

    def test_delete_nonexistent_items_api(
        self,
        sample_team_with_owner_member: Member,
        sample_access_token: AccessToken,
    ):
        """Test deleting non-existent items returns 404."""
        client = Client()

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, sample_team_with_owner_member.team, sample_team_with_owner_member.user)

        # Test deleting non-existent product
        response = client.delete(
            reverse("api-1:delete_product", kwargs={"product_id": "nonexistent"}),
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 404

        # Test deleting non-existent project
        response = client.delete(
            reverse("api-1:delete_project", kwargs={"project_id": "nonexistent"}),
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 404

        # Test deleting non-existent component
        response = client.delete(
            reverse("api-1:delete_component", kwargs={"component_id": "nonexistent"}),
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestDuplicateNamesAPI:
    """Test duplicate name validation at the API level."""

    def test_create_duplicate_product_name_api(
        self,
        sample_team_with_owner_member: Member,
        sample_access_token: AccessToken,
        sample_billing_plan: BillingPlan,
    ):
        """Test that creating a product with duplicate name fails via API."""
        client = Client()
        team = sample_team_with_owner_member.team
        team.billing_plan = sample_billing_plan.key
        team.save()

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, team, sample_team_with_owner_member.user)

        # Create first product via API
        url = reverse("api-1:create_product")
        payload = {"name": "Duplicate Product"}

        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Try to create second product with same name
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

        # Verify only one product exists
        assert Product.objects.filter(team=team, name="Duplicate Product").count() == 1

    def test_create_duplicate_project_name_api(
        self,
        sample_team_with_owner_member: Member,
        sample_access_token: AccessToken,
        sample_billing_plan: BillingPlan,
    ):
        """Test that creating a project with duplicate name fails via API."""
        client = Client()
        team = sample_team_with_owner_member.team
        team.billing_plan = sample_billing_plan.key
        team.save()

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, team, sample_team_with_owner_member.user)

        # Create first project via API
        url = reverse("api-1:create_project")
        payload = {"name": "Duplicate Project", "metadata": {}}

        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Try to create second project with same name
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

        # Verify only one project exists
        assert Project.objects.filter(team=team, name="Duplicate Project").count() == 1

    def test_create_duplicate_component_name_api(
        self,
        sample_team_with_owner_member: Member,
        sample_access_token: AccessToken,
        sample_billing_plan: BillingPlan,
    ):
        """Test that creating a component with duplicate name fails via API."""
        client = Client()
        team = sample_team_with_owner_member.team
        team.billing_plan = sample_billing_plan.key
        team.save()

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, team, sample_team_with_owner_member.user)

        # Create first component via API
        url = reverse("api-1:create_component")
        payload = {"name": "Duplicate Component", "metadata": {}}

        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Try to create second component with same name
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

        # Verify only one component exists
        assert Component.objects.filter(team=team, name="Duplicate Component").count() == 1


@pytest.mark.django_db
class TestBillingPlanLimitsAPI:
    """Test billing plan enforcement at the API level."""

    def _setup_team_with_plan(self, team: Member, plan_data: dict) -> BillingPlan:
        """Helper to set up team with billing plan."""
        plan = BillingPlan.objects.create(**plan_data)
        team.billing_plan = plan.key
        team.save()
        return plan

    def test_product_creation_limits_api(
        self,
        sample_team_with_owner_member: Member,
        sample_access_token: AccessToken,
    ):
        """Test product creation limits via API."""
        client = Client()
        team = sample_team_with_owner_member.team

        # Set up limited billing plan
        plan = self._setup_team_with_plan(team, {
            "key": "limited_product_plan",
            "name": "Limited Product Plan",
            "max_products": 2,
            "max_projects": 10,
            "max_components": 10
        })

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, team, sample_team_with_owner_member.user)

        url = reverse("api-1:create_product")

        # Create up to limit
        for i in range(plan.max_products):
            payload = {"name": f"Product {i+1}"}
            response = client.post(
                url,
                json.dumps(payload),
                content_type="application/json",
                **get_api_headers(sample_access_token),
            )
            assert response.status_code == 201

        # Try to exceed limit
        payload = {"name": "Over Limit Product"}
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 403
        error_detail = response.json()["detail"]
        assert f"maximum {plan.max_products} products" in error_detail

    def test_project_creation_limits_api(
        self,
        sample_team_with_owner_member: Member,
        sample_access_token: AccessToken,
    ):
        """Test project creation limits via API."""
        client = Client()
        team = sample_team_with_owner_member.team

        # Set up limited billing plan
        plan = self._setup_team_with_plan(team, {
            "key": "limited_project_plan",
            "name": "Limited Project Plan",
            "max_products": 10,
            "max_projects": 1,
            "max_components": 10
        })

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, team, sample_team_with_owner_member.user)

        url = reverse("api-1:create_project")

        # Create up to limit
        payload = {"name": "Project 1", "metadata": {}}
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Try to exceed limit
        payload = {"name": "Over Limit Project", "metadata": {}}
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 403
        error_detail = response.json()["detail"]
        assert f"maximum {plan.max_projects} projects" in error_detail

    def test_component_creation_limits_api(
        self,
        sample_team_with_owner_member: Member,
        sample_access_token: AccessToken,
    ):
        """Test component creation limits via API."""
        client = Client()
        team = sample_team_with_owner_member.team

        # Set up limited billing plan
        plan = self._setup_team_with_plan(team, {
            "key": "limited_component_plan",
            "name": "Limited Component Plan",
            "max_products": 10,
            "max_projects": 10,
            "max_components": 3
        })

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, team, sample_team_with_owner_member.user)

        url = reverse("api-1:create_component")

        # Create up to limit
        for i in range(plan.max_components):
            payload = {"name": f"Component {i+1}", "metadata": {}}
            response = client.post(
                url,
                json.dumps(payload),
                content_type="application/json",
                **get_api_headers(sample_access_token),
            )
            assert response.status_code == 201

        # Try to exceed limit
        payload = {"name": "Over Limit Component", "metadata": {}}
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 403
        error_detail = response.json()["detail"]
        assert f"maximum {plan.max_components} components" in error_detail

    def test_unlimited_plan_allows_creation_api(
        self,
        sample_team_with_owner_member: Member,
        sample_access_token: AccessToken,
    ):
        """Test unlimited plan allows creation beyond default limits via API."""
        client = Client()
        team = sample_team_with_owner_member.team

        # Set up unlimited billing plan
        self._setup_team_with_plan(team, {
            "key": "unlimited",
            "name": "Unlimited Plan",
            "max_products": None,
            "max_projects": None,
            "max_components": None
        })

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, team, sample_team_with_owner_member.user)

        # Create multiple resources beyond typical limits
        for i in range(5):
            # Create product
            response = client.post(
                reverse("api-1:create_product"),
                json.dumps({"name": f"Product {i+1}"}),
                content_type="application/json",
                **get_api_headers(sample_access_token),
            )
            assert response.status_code == 201

            # Create project
            response = client.post(
                reverse("api-1:create_project"),
                json.dumps({"name": f"Project {i+1}", "metadata": {}}),
                content_type="application/json",
                **get_api_headers(sample_access_token),
            )
            assert response.status_code == 201

            # Create component
            response = client.post(
                reverse("api-1:create_component"),
                json.dumps({"name": f"Component {i+1}", "metadata": {}}),
                content_type="application/json",
                **get_api_headers(sample_access_token),
            )
            assert response.status_code == 201

        # Verify all resources were created
        assert Product.objects.filter(team=team).count() == 5
        assert Project.objects.filter(team=team).count() == 5
        assert Component.objects.filter(team=team).count() == 5

    def test_no_plan_blocks_creation_api(
        self,
        sample_team_with_owner_member: Member,
        sample_access_token: AccessToken,
    ):
        """Test resource creation fails when no billing plan exists via API."""
        client = Client()
        team = sample_team_with_owner_member.team

        # Remove billing plan
        team.billing_plan = None
        team.save()

        # Set up authentication and session
        assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
        setup_test_session(client, team, sample_team_with_owner_member.user)

        # Test product creation blocked
        response = client.post(
            reverse("api-1:create_product"),
            json.dumps({"name": "Test Product"}),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 403
        assert "No active billing plan" in response.json()["detail"]

        # Test project creation blocked
        response = client.post(
            reverse("api-1:create_project"),
            json.dumps({"name": "Test Project", "metadata": {}}),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 403
        assert "No active billing plan" in response.json()["detail"]

        # Test component creation blocked
        response = client.post(
            reverse("api-1:create_component"),
            json.dumps({"name": "Test Component", "metadata": {}}),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 403
        assert "No active billing plan" in response.json()["detail"]


# =============================================================================
# PRODUCT IDENTIFIER CRUD TESTS
# =============================================================================


@pytest.mark.django_db
def test_create_product_identifier_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful product identifier creation."""
    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    payload = {"identifier_type": "sku", "value": "SKU123456"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["identifier_type"] == "sku"
    assert data["value"] == "SKU123456"
    assert "id" in data
    assert "created_at" in data

    # Verify identifier was created in database
    identifier = ProductIdentifier.objects.get(id=data["id"])
    assert identifier.identifier_type == "sku"
    assert identifier.value == "SKU123456"
    assert identifier.product_id == sample_product.id
    assert identifier.team_id == sample_product.team_id


@pytest.mark.django_db
def test_create_product_identifier_duplicate_value(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test creating duplicate identifier fails."""
    # Create initial identifier
    ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="sku",
        value="SKU123456",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    payload = {"identifier_type": "sku", "value": "SKU123456"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.django_db
def test_list_product_identifiers_authenticated(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test listing identifiers for authenticated users."""
    # Create test identifiers
    identifier1 = ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="sku",
        value="SKU123456",
    )
    identifier2 = ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="gtin_12",
        value="123456789012",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) == 2

    # Check identifiers are in response
    identifier_ids = [item["id"] for item in data["items"]]
    assert identifier1.id in identifier_ids
    assert identifier2.id in identifier_ids


@pytest.mark.django_db
def test_list_product_identifiers_public_product(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test listing identifiers for public products without authentication."""
    # Create a public product
    product = Product.objects.create(
        name="Public Product",
        team=sample_team_with_owner_member.team,
        is_public=True,
    )

    # Create test identifier
    identifier = ProductIdentifier.objects.create(
        product=product,
        team=product.team,
        identifier_type="sku",
        value="PUBLIC-SKU-123",
    )

    client = Client()
    url = f"/api/v1/products/{product.id}/identifiers"

    response = client.get(url)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == identifier.id
    assert data["items"][0]["value"] == "PUBLIC-SKU-123"


@pytest.mark.django_db
def test_list_product_identifiers_private_product_no_auth(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test listing identifiers for private products requires authentication."""
    # Create a private product
    product = Product.objects.create(
        name="Private Product",
        team=sample_team_with_owner_member.team,
        is_public=False,
    )

    client = Client()
    url = f"/api/v1/products/{product.id}/identifiers"

    response = client.get(url)

    assert response.status_code == 403
    assert "Authentication required" in response.json()["detail"]


@pytest.mark.django_db
def test_update_product_identifier_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful product identifier update."""
    # Create test identifier
    identifier = ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="sku",
        value="SKU123456",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers/{identifier.id}"

    payload = {"identifier_type": "mpn", "value": "MPN789012"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["identifier_type"] == "mpn"
    assert data["value"] == "MPN789012"

    # Verify update in database
    identifier.refresh_from_db()
    assert identifier.identifier_type == "mpn"
    assert identifier.value == "MPN789012"


@pytest.mark.django_db
def test_delete_product_identifier_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful product identifier deletion."""
    # Create test identifier
    identifier = ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="sku",
        value="SKU123456",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers/{identifier.id}"

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.delete(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Verify deletion in database
    assert not ProductIdentifier.objects.filter(id=identifier.id).exists()


@pytest.mark.django_db
def test_bulk_update_product_identifiers_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful bulk update of product identifiers."""
    # Create existing identifiers
    identifier1 = ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="sku",
        value="OLD-SKU",
    )
    identifier2 = ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="mpn",
        value="OLD-MPN",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    payload = {
        "identifiers": [
            {"identifier_type": "sku", "value": "NEW-SKU-123"},
            {"identifier_type": "gtin_12", "value": "123456789012"},
            {"identifier_type": "asin", "value": "B08N5WRWNW"},
        ]
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3

    # Verify old identifiers are deleted
    assert not ProductIdentifier.objects.filter(id=identifier1.id).exists()
    assert not ProductIdentifier.objects.filter(id=identifier2.id).exists()

    # Verify new identifiers are created
    identifiers = ProductIdentifier.objects.filter(product=sample_product)
    assert identifiers.count() == 3

    values = list(identifiers.values_list("value", flat=True))
    assert "NEW-SKU-123" in values
    assert "123456789012" in values
    assert "B08N5WRWNW" in values


@pytest.mark.django_db
def test_product_identifier_permissions(
    sample_team_with_guest_member: Member,  # noqa: F811
):
    """Test that only owners and admins can manage product identifiers."""
    from access_tokens.utils import create_personal_access_token
    from access_tokens.models import AccessToken

    # Use the provided guest member
    guest_member = sample_team_with_guest_member

    # Create access token for the guest user
    guest_token_str = create_personal_access_token(guest_member.user)
    guest_access_token = AccessToken.objects.create(
        user=guest_member.user,
        encoded_token=guest_token_str,
        description="Guest Test API Token"
    )

    # Create product
    product = Product.objects.create(
        name="Test Product",
        team=guest_member.team,
    )

    client = Client()
    url = f"/api/v1/products/{product.id}/identifiers"

    payload = {"identifier_type": "sku", "value": "SKU123456"}

    # Test with guest user - should be forbidden due to role permissions
    assert client.login(username=guest_member.user.username, password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, guest_member.team, guest_member.user)

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(guest_access_token),
    )

    assert response.status_code == 403
    assert "Only owners and admins" in response.json()["detail"]

    # Clean up
    guest_access_token.delete()


@pytest.mark.django_db
def test_product_identifier_not_found(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test operations on non-existent identifiers."""
    client = Client()

    # Test update non-existent identifier
    url = f"/api/v1/products/{sample_product.id}/identifiers/nonexistent"
    payload = {"identifier_type": "sku", "value": "NEW-VALUE"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

    # Test delete non-existent identifier
    response = client.delete(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.django_db(transaction=True)
def test_product_identifier_validation(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test validation of product identifier fields."""
    import uuid
    from sboms.models import ProductIdentifier
    from django.db import IntegrityError, transaction

    unique_suffix = str(uuid.uuid4())[:8]

    # Clean up any existing identifiers for this team to avoid conflicts
    ProductIdentifier.objects.filter(team=sample_team_with_owner_member.team).delete()

    product = Product.objects.create(
        name=f"Test Product {unique_suffix}",
        team=sample_team_with_owner_member.team,
    )

    # Test unique constraint within team
    identifier1 = ProductIdentifier.objects.create(
        product=product,
        team=sample_team_with_owner_member.team,
        identifier_type="sku",
        value=f"VALIDATION-SKU-{unique_suffix}",
    )

    # Creating another identifier with same type and value in same team should fail
    # Use separate atomic block for this test to handle the rollback
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ProductIdentifier.objects.create(
                product=product,
                team=sample_team_with_owner_member.team,
                identifier_type="sku",
                value=f"VALIDATION-SKU-{unique_suffix}",
            )

    # But same value with different type should be allowed
    identifier2 = ProductIdentifier.objects.create(
        product=product,
        team=sample_team_with_owner_member.team,
        identifier_type="mpn",
        value=f"VALIDATION-MPN-{unique_suffix}",  # Use different value to avoid confusion
    )

    assert identifier1.id != identifier2.id


@pytest.mark.django_db
def test_product_with_identifiers_in_response(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that product responses include identifiers."""
    # Create test identifiers
    identifier1 = ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="sku",
        value="SKU123456",
    )
    identifier2 = ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="gtin_12",
        value="123456789012",
    )

    client = Client()
    url = reverse("api-1:get_product", kwargs={"product_id": sample_product.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert "identifiers" in data
    assert isinstance(data["identifiers"], list)
    assert len(data["identifiers"]) == 2

    # Check identifiers data structure
    identifier_ids = [item["id"] for item in data["identifiers"]]
    assert identifier1.id in identifier_ids
    assert identifier2.id in identifier_ids

    # Check identifier fields
    for identifier_data in data["identifiers"]:
        assert "id" in identifier_data
        assert "identifier_type" in identifier_data
        assert "value" in identifier_data
        assert "created_at" in identifier_data


@pytest.mark.django_db
def test_product_identifier_billing_restrictions(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that product identifiers are restricted to business and enterprise plans."""
    # Set product team to community plan
    sample_product.team.billing_plan = "community"
    sample_product.team.save()

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    payload = {"identifier_type": "sku", "value": "SKU123456"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test create - should be forbidden for community plan
    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 403
    assert "business and enterprise plans" in response.json()["detail"]
    assert response.json()["error_code"] == "BILLING_LIMIT_EXCEEDED"

    # Create identifier directly for testing update/delete restrictions
    from sboms.models import ProductIdentifier
    identifier = ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="sku",
        value="SKU123456",
    )

    # Test update - should be forbidden for community plan
    update_url = f"/api/v1/products/{sample_product.id}/identifiers/{identifier.id}"
    update_payload = {"identifier_type": "mpn", "value": "MPN789012"}

    response = client.put(
        update_url,
        json.dumps(update_payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 403
    assert "business and enterprise plans" in response.json()["detail"]

    # Test delete - should be forbidden for community plan
    response = client.delete(
        update_url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 403
    assert "business and enterprise plans" in response.json()["detail"]

    # Test bulk update - should be forbidden for community plan
    bulk_payload = {
        "identifiers": [
            {"identifier_type": "sku", "value": "NEW-SKU-123"},
            {"identifier_type": "gtin_12", "value": "123456789012"},
        ]
    }

    response = client.put(
        url,
        json.dumps(bulk_payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 403
    assert "business and enterprise plans" in response.json()["detail"]


@pytest.mark.django_db
def test_product_identifier_business_plan_allowed(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that product identifiers work for business plan users."""
    # Set product team to business plan
    sample_product.team.billing_plan = "business"
    sample_product.team.save()

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    payload = {"identifier_type": "sku", "value": "SKU123456"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test create - should work for business plan
    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    assert response.json()["identifier_type"] == "sku"
    assert response.json()["value"] == "SKU123456"


@pytest.mark.django_db
def test_product_identifier_enterprise_plan_allowed(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that product identifiers work for enterprise plan users."""
    # Set product team to enterprise plan
    sample_product.team.billing_plan = "enterprise"
    sample_product.team.save()

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    payload = {"identifier_type": "sku", "value": "SKU123456"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test create - should work for enterprise plan
    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    assert response.json()["identifier_type"] == "sku"
    assert response.json()["value"] == "SKU123456"


@pytest.mark.django_db
def test_product_identifier_billing_disabled(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    mocker,  # noqa: F811
):
    """Test that product identifiers work when billing is disabled."""
    # Mock billing as disabled
    mocker.patch('core.apis.is_billing_enabled', return_value=False)

    # Set product team to community plan (should be ignored when billing is disabled)
    sample_product.team.billing_plan = "community"
    sample_product.team.save()

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    payload = {"identifier_type": "sku", "value": "SKU123456"}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test create - should work when billing is disabled
    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    assert response.json()["identifier_type"] == "sku"
    assert response.json()["value"] == "SKU123456"


@pytest.mark.django_db
def test_product_identifier_public_access(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that product identifiers are visible on public product pages."""
    # Set product to business plan and create some identifiers
    sample_product.team.billing_plan = "business"
    sample_product.team.save()

    # Make the product public
    sample_product.is_public = True
    sample_product.save()

    client = Client()

    # Set up authentication and session for creating identifiers
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Create a few identifiers
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    identifiers_data = [
        {"identifier_type": "sku", "value": "SKU-PUBLIC-123"},
        {"identifier_type": "gtin_13", "value": "1234567890123"},
        {"identifier_type": "mpn", "value": "MPN-ABC-456"}
    ]

    for payload in identifiers_data:
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

    # Now test public access (without authentication)
    client.logout()

    # Test that unauthenticated users can view identifiers for public products
    response = client.get(url)

    assert response.status_code == 200
    response_data = response.json()
    assert "items" in response_data
    assert "pagination" in response_data
    assert len(response_data["items"]) == 3

    # Verify the identifiers are returned correctly
    identifier_values = [item["value"] for item in response_data["items"]]
    assert "SKU-PUBLIC-123" in identifier_values
    assert "1234567890123" in identifier_values
    assert "MPN-ABC-456" in identifier_values

    # Verify all expected fields are present
    for identifier in response_data["items"]:
        assert "id" in identifier
        assert "identifier_type" in identifier
        assert "value" in identifier
        assert "created_at" in identifier


@pytest.mark.django_db
def test_product_identifier_private_access_denied(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that identifiers for private products are not accessible without permissions."""
    from teams.models import Team, Member

    # Set product team to business plan to allow identifiers
    sample_product.team.billing_plan = "business"
    sample_product.team.save()

    # Make product private
    sample_product.is_public = False
    sample_product.save()

    # Create a test identifier
    ProductIdentifier.objects.create(
        product=sample_product,
        team=sample_product.team,
        identifier_type="sku",
        value="PRIVATE-SKU-123",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/identifiers"

    # Test without authentication - should be forbidden
    response = client.get(url)
    assert response.status_code == 403
    assert "Authentication required" in response.json()["detail"]

    # Test with authentication but as a user from different team
    different_user = User.objects.create_user(
        username="different_user",
        email="different@example.com",
        password=os.environ["DJANGO_TEST_PASSWORD"],
    )

    # Create a different team for this user
    different_team = Team.objects.create(name="Different Team", billing_plan="business")
    Member.objects.create(user=different_user, team=different_team, role="owner")

    assert client.login(username="different_user", password=os.environ["DJANGO_TEST_PASSWORD"])

    # Set up session for the different user with their own team
    from sboms.tests.test_views import setup_test_session
    setup_test_session(client, different_team, different_user)

    response = client.get(url)

    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


# =============================================================================
# PRODUCT LINK CRUD TESTS
# =============================================================================


@pytest.mark.django_db
def test_create_product_link_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful product link creation."""
    client = Client()
    url = f"/api/v1/products/{sample_product.id}/links"

    payload = {
        "link_type": "website",
        "title": "Official Website",
        "url": "https://example.com",
        "description": "The official company website"
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["link_type"] == "website"
    assert data["title"] == "Official Website"
    assert data["url"] == "https://example.com"
    assert data["description"] == "The official company website"
    assert "id" in data
    assert "created_at" in data

    # Verify link was created in database
    link = ProductLink.objects.get(id=data["id"])
    assert link.link_type == "website"
    assert link.title == "Official Website"
    assert link.url == "https://example.com"
    assert link.description == "The official company website"
    assert link.product_id == sample_product.id
    assert link.team_id == sample_product.team_id


@pytest.mark.django_db
def test_create_product_link_duplicate_url(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test creating duplicate link fails."""
    # Create initial link
    ProductLink.objects.create(
        product=sample_product,
        team=sample_product.team,
        link_type="website",
        title="Official Website",
        url="https://example.com",
        description="Test description",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/links"

    payload = {
        "link_type": "website",
        "title": "Another Website",
        "url": "https://example.com",
        "description": "Another description"
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.django_db
def test_list_product_links_authenticated(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test listing links for authenticated users."""
    # Create test links
    link1 = ProductLink.objects.create(
        product=sample_product,
        team=sample_product.team,
        link_type="website",
        title="Official Website",
        url="https://example.com",
        description="Company website",
    )
    link2 = ProductLink.objects.create(
        product=sample_product,
        team=sample_product.team,
        link_type="support",
        title="Support Portal",
        url="https://support.example.com",
        description="Get help and support",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/links"

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) == 2

    # Check links are in response
    link_ids = [item["id"] for item in data["items"]]
    assert link1.id in link_ids
    assert link2.id in link_ids


@pytest.mark.django_db
def test_list_product_links_public_product(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test listing links for public products without authentication."""
    # Create a public product
    product = Product.objects.create(
        name="Public Product",
        team=sample_team_with_owner_member.team,
        is_public=True,
    )

    # Create test link
    link = ProductLink.objects.create(
        product=product,
        team=product.team,
        link_type="website",
        title="Public Website",
        url="https://public.example.com",
        description="Public website",
    )

    client = Client()
    url = f"/api/v1/products/{product.id}/links"

    response = client.get(url)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == link.id
    assert data["items"][0]["title"] == "Public Website"
    assert data["items"][0]["url"] == "https://public.example.com"


@pytest.mark.django_db
def test_list_product_links_private_product_no_auth(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test listing links for private products requires authentication."""
    # Create a private product
    product = Product.objects.create(
        name="Private Product",
        team=sample_team_with_owner_member.team,
        is_public=False,
    )

    client = Client()
    url = f"/api/v1/products/{product.id}/links"

    response = client.get(url)

    assert response.status_code == 403
    assert "Authentication required" in response.json()["detail"]


@pytest.mark.django_db
def test_update_product_link_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful product link update."""
    # Create test link
    link = ProductLink.objects.create(
        product=sample_product,
        team=sample_product.team,
        link_type="website",
        title="Old Website",
        url="https://old.example.com",
        description="Old description",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/links/{link.id}"

    payload = {
        "link_type": "support",
        "title": "New Support Portal",
        "url": "https://support.example.com",
        "description": "Updated support portal"
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["link_type"] == "support"
    assert data["title"] == "New Support Portal"
    assert data["url"] == "https://support.example.com"
    assert data["description"] == "Updated support portal"

    # Verify update in database
    link.refresh_from_db()
    assert link.link_type == "support"
    assert link.title == "New Support Portal"
    assert link.url == "https://support.example.com"
    assert link.description == "Updated support portal"


@pytest.mark.django_db
def test_delete_product_link_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful product link deletion."""
    # Create test link
    link = ProductLink.objects.create(
        product=sample_product,
        team=sample_product.team,
        link_type="website",
        title="Website to Delete",
        url="https://delete.example.com",
        description="This will be deleted",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/links/{link.id}"

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.delete(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Verify deletion in database
    assert not ProductLink.objects.filter(id=link.id).exists()


@pytest.mark.django_db
def test_bulk_update_product_links_success(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test successful bulk update of product links."""
    # Create existing links
    link1 = ProductLink.objects.create(
        product=sample_product,
        team=sample_product.team,
        link_type="website",
        title="Old Website",
        url="https://old.example.com",
        description="Old website",
    )
    link2 = ProductLink.objects.create(
        product=sample_product,
        team=sample_product.team,
        link_type="support",
        title="Old Support",
        url="https://oldsupport.example.com",
        description="Old support",
    )

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/links"

    payload = {
        "links": [
            {
                "link_type": "website",
                "title": "New Official Website",
                "url": "https://new.example.com",
                "description": "Our new website"
            },
            {
                "link_type": "documentation",
                "title": "Documentation",
                "url": "https://docs.example.com",
                "description": "Product documentation"
            },
            {
                "link_type": "repository",
                "title": "Source Code",
                "url": "https://github.com/example/product",
                "description": "Open source repository"
            }
        ]
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3

    # Verify old links are deleted
    assert not ProductLink.objects.filter(id=link1.id).exists()
    assert not ProductLink.objects.filter(id=link2.id).exists()

    # Verify new links are created
    links = ProductLink.objects.filter(product=sample_product)
    assert links.count() == 3

    titles = list(links.values_list("title", flat=True))
    assert "New Official Website" in titles
    assert "Documentation" in titles
    assert "Source Code" in titles


@pytest.mark.django_db
def test_product_link_permissions(
    sample_team_with_guest_member: Member,  # noqa: F811
):
    """Test that only owners and admins can manage product links."""
    from access_tokens.utils import create_personal_access_token
    from access_tokens.models import AccessToken

    # Use the provided guest member
    guest_member = sample_team_with_guest_member

    # Create access token for the guest user
    guest_token_str = create_personal_access_token(guest_member.user)
    guest_access_token = AccessToken.objects.create(
        user=guest_member.user,
        encoded_token=guest_token_str,
        description="Guest Test API Token"
    )

    # Create product
    product = Product.objects.create(
        name="Test Product",
        team=guest_member.team,
    )

    client = Client()
    url = f"/api/v1/products/{product.id}/links"

    payload = {
        "link_type": "website",
        "title": "Test Website",
        "url": "https://test.example.com",
        "description": "Test description"
    }

    # Test with guest user - should be forbidden due to role permissions
    assert client.login(username=guest_member.user.username, password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, guest_member.team, guest_member.user)

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(guest_access_token),
    )

    assert response.status_code == 403
    assert "Only owners and admins" in response.json()["detail"]

    # Clean up
    guest_access_token.delete()


@pytest.mark.django_db
def test_product_link_not_found(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test operations on non-existent links."""
    client = Client()

    # Test update non-existent link
    url = f"/api/v1/products/{sample_product.id}/links/nonexistent"
    payload = {
        "link_type": "website",
        "title": "Updated Title",
        "url": "https://new.example.com",
        "description": "Updated description"
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

    # Test delete non-existent link
    response = client.delete(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.django_db(transaction=True)
def test_product_link_validation(
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test validation of product link fields."""
    import uuid
    from django.db import IntegrityError, transaction

    unique_suffix = str(uuid.uuid4())[:8]

    product = Product.objects.create(
        name=f"Test Product {unique_suffix}",
        team=sample_team_with_owner_member.team,
    )

    # Test unique constraint within team
    link1 = ProductLink.objects.create(
        product=product,
        team=sample_team_with_owner_member.team,
        link_type="website",
        title="Website",
        url=f"https://unique-{unique_suffix}.example.com",
        description="Unique URL",
    )

    # Creating another link with same type and URL in same team should fail
    # Use separate atomic block for this test to handle the rollback
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ProductLink.objects.create(
                product=product,
                team=sample_team_with_owner_member.team,
                link_type="website",
                title="Another Website",
                url=f"https://unique-{unique_suffix}.example.com",
                description="Duplicate URL",
            )

    # But same URL with different type should be allowed
    link2 = ProductLink.objects.create(
        product=product,
        team=sample_team_with_owner_member.team,
        link_type="support",
        title="Support",
        url="https://different.example.com",
        description="Different URL",
    )

    assert link1.id != link2.id


@pytest.mark.django_db
def test_product_with_links_in_response(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that product responses include links."""
    # Create test links
    link1 = ProductLink.objects.create(
        product=sample_product,
        team=sample_product.team,
        link_type="website",
        title="Official Website",
        url="https://example.com",
        description="Company website",
    )
    link2 = ProductLink.objects.create(
        product=sample_product,
        team=sample_product.team,
        link_type="support",
        title="Support Portal",
        url="https://support.example.com",
        description="Get help",
    )

    client = Client()
    url = reverse("api-1:get_product", kwargs={"product_id": sample_product.id})

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.get(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert "links" in data
    assert isinstance(data["links"], list)
    assert len(data["links"]) == 2

    # Check links data structure
    link_ids = [item["id"] for item in data["links"]]
    assert link1.id in link_ids
    assert link2.id in link_ids

    # Check link fields
    for link_data in data["links"]:
        assert "id" in link_data
        assert "link_type" in link_data
        assert "title" in link_data
        assert "url" in link_data
        assert "description" in link_data
        assert "created_at" in link_data


@pytest.mark.django_db
def test_product_link_no_billing_restrictions(
    sample_product: Product,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that product links are available regardless of billing plan."""
    # Set product team to community plan
    sample_product.team.billing_plan = "community"
    sample_product.team.save()

    client = Client()
    url = f"/api/v1/products/{sample_product.id}/links"

    payload = {
        "link_type": "website",
        "title": "Community Website",
        "url": "https://community.example.com",
        "description": "Available on community plan"
    }

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test create - should succeed even on community plan
    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Community Website"

    # Test update - should also succeed
    link_id = data["id"]
    update_payload = {
        "link_type": "support",
        "title": "Community Support",
        "url": "https://support.community.example.com",
        "description": "Support for community users"
    }

    response = client.put(
        f"{url}/{link_id}",
        json.dumps(update_payload),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Community Support"

    # Test delete - should also succeed
    response = client.delete(
        f"{url}/{link_id}",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204
