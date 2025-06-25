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
from core.tests.fixtures import sample_user  # noqa: F401
from teams.fixtures import sample_team_with_owner_member  # noqa: F401
from teams.models import Member

from ..models import Component, Product, Project
from .fixtures import (  # noqa: F401
    sample_access_token,
    sample_billing_plan,
    sample_component,
    sample_product,
    sample_project,
)
from .test_views import setup_test_session

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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == sample_product.id
    assert data[0]["name"] == sample_product.name


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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
    """Test linking projects to a product."""
    client = Client()
    url = reverse("api-1:link_projects_to_product", kwargs={"product_id": sample_product.id})

    # Ensure project is in same team
    sample_project.team = sample_product.team
    sample_project.save()

    payload = {"project_ids": [sample_project.id]}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 204

    # Verify link in database
    assert sample_product.projects.filter(id=sample_project.id).exists()


@pytest.mark.django_db
def test_unlink_projects_from_product(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test unlinking projects from a product."""
    client = Client()

    # Ensure project is in same team and linked to product
    sample_project.team = sample_product.team
    sample_project.save()
    sample_product.projects.add(sample_project)

    url = reverse("api-1:unlink_projects_from_product", kwargs={"product_id": sample_product.id})
    payload = {"project_ids": [sample_project.id]}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    response = client.delete(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 204

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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == sample_project.id


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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
    """Test linking components to a project."""
    client = Client()
    url = reverse("api-1:link_components_to_project", kwargs={"project_id": sample_project.id})

    # Ensure component is in same team
    sample_component.team = sample_project.team
    sample_component.save()

    payload = {"component_ids": [sample_component.id]}

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    response = client.post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 204

    # Verify link in database
    assert sample_project.components.filter(id=sample_component.id).exists()


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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == sample_component.id


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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 204

    # Verify deletion in database
    assert not Component.objects.filter(id=sample_component.id).exists()


# =============================================================================
# AUTHORIZATION TESTS
# =============================================================================


@pytest.mark.django_db
def test_crud_operations_require_authentication():
    """Test that all CRUD operations require authentication."""
    client = Client()

    urls = [
        reverse("api-1:create_product"),
        reverse("api-1:list_products"),
        reverse("api-1:create_project"),
        reverse("api-1:list_projects"),
        reverse("api-1:create_component"),
        reverse("api-1:list_components"),
    ]

    for url in urls:
        response = client.get(url)
        assert response.status_code in [401, 403]  # Unauthorized or Forbidden

        response = client.post(url, json.dumps({"name": "test"}), content_type="application/json")
        assert response.status_code in [401, 403]


@pytest.mark.django_db
def test_crud_operations_require_team_access(
    sample_access_token: AccessToken,  # noqa: F811
    sample_team_with_owner_member: Member,  # noqa: F811
):
    """Test that CRUD operations require proper team access."""
    client = Client()

    # Set up authentication but no team session
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

    list_urls = [
        reverse("api-1:list_products"),
        reverse("api-1:list_projects"),
        reverse("api-1:list_components"),
    ]

    payload = {"name": "Test Item"}

    # Test create operations
    for url in create_urls:
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 403
        assert "No current team selected" in response.json()["detail"]

    # Test list operations
    for url in list_urls:
        response = client.get(
            url,
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 403
        assert "No current team selected" in response.json()["detail"]


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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 404

        # Test deleting non-existent project
        response = client.delete(
            reverse("api-1:delete_project", kwargs={"project_id": "nonexistent"}),
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 404

        # Test deleting non-existent component
        response = client.delete(
            reverse("api-1:delete_component", kwargs={"component_id": "nonexistent"}),
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 201

        # Try to create second product with same name
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 201

        # Try to create second project with same name
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 201

        # Try to create second component with same name
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
                HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
            )
            assert response.status_code == 201

        # Try to exceed limit
        payload = {"name": "Over Limit Product"}
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 201

        # Try to exceed limit
        payload = {"name": "Over Limit Project", "metadata": {}}
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
                HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
            )
            assert response.status_code == 201

        # Try to exceed limit
        payload = {"name": "Over Limit Component", "metadata": {}}
        response = client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
                HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
            )
            assert response.status_code == 201

            # Create project
            response = client.post(
                reverse("api-1:create_project"),
                json.dumps({"name": f"Project {i+1}", "metadata": {}}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
            )
            assert response.status_code == 201

            # Create component
            response = client.post(
                reverse("api-1:create_component"),
                json.dumps({"name": f"Component {i+1}", "metadata": {}}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
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
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 403
        assert "No active billing plan" in response.json()["detail"]

        # Test project creation blocked
        response = client.post(
            reverse("api-1:create_project"),
            json.dumps({"name": "Test Project", "metadata": {}}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 403
        assert "No active billing plan" in response.json()["detail"]

        # Test component creation blocked
        response = client.post(
            reverse("api-1:create_component"),
            json.dumps({"name": "Test Component", "metadata": {}}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
        )
        assert response.status_code == 403
        assert "No active billing plan" in response.json()["detail"]
