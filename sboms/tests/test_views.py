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
    sample_access_token,  # noqa: F401
    sample_component,  # noqa: F401
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

    # Set up session data
    session = client.session
    session["user_teams"] = {
        team.key: {
            "role": role,
            "name": team.name,
            "is_default_team": member.is_default_team
        }
    }
    session["current_team"] = {
        "key": team.key,
        "role": role,
        "name": team.name,
        "is_default_team": member.is_default_team
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
def test_create_product(sample_team_with_owner_member):  # Changed fixture
    client = Client()
    team = sample_team_with_owner_member.team

    # Set valid team key that encodes the team ID
    team.key = number_to_random_token(team.id)
    team.save()

    # Setup default billing plan
    BillingPlan.objects.create(
        key="default_plan",
        name="Default Plan",
        max_products=10,
        max_projects=10,
        max_components=10
    )
    team.billing_plan = "default_plan"
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["current_team"] = {"id": team.id, "role": "owner", "key": team.key}
    session.save()

    response = client.post(
        reverse("sboms:products_dashboard"),
        {"name": "Test Product"}
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_delete_product(sample_team_with_owner_member):
    client = Client()
    team = sample_team_with_owner_member.team

    team.key = number_to_random_token(team.id)
    team.save()

    BillingPlan.objects.create(
        key="delete_product_plan",
        name="Delete Product Plan",
        max_products=10,
        max_projects=10,
        max_components=10
    )
    team.billing_plan = "delete_product_plan"
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["user_teams"] = {
        team.key: {"role": "owner", "name": team.name}
    }
    session["current_team"] = {
        "key": team.key,
        "role": "owner",
        "name": team.name
    }
    session.save()

    # Create product
    response = client.post(
        reverse("sboms:products_dashboard"),
        {"name": "Test Product"}
    )
    assert response.status_code == 302

    # Delete product
    product_id = Product.objects.first().id
    response = client.get(
        reverse("sboms:delete_product", kwargs={"product_id": product_id})
    )
    assert response.status_code == 302

    # Verify product is deleted
    assert not Product.objects.filter(pk=product_id).exists()

    # Check success messages
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 2
    assert str(messages[0]) == "Product Test Product created"
    assert str(messages[1]) == "Product Test Product deleted"


@pytest.mark.django_db
def test_create_project(sample_team_with_owner_member):
    client = Client()
    team = sample_team_with_owner_member.team

    team.key = number_to_random_token(team.id)
    team.save()

    BillingPlan.objects.create(
        key="default_plan",
        name="Default Plan",
        max_projects=10,
        max_products=10,
        max_components=10
    )
    team.billing_plan = "default_plan"
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["current_team"] = {"id": team.id, "role": "owner", "key": team.key}
    session.save()

    response = client.post(
        reverse("sboms:projects_dashboard"),
        {"name": "Test Project"}
    )
    assert response.status_code == 302

    messages = list(response.wsgi_request._messages)
    assert len(messages) == 1
    assert str(messages[0]) == "Project Test Project created"


@pytest.mark.django_db
def test_delete_project(sample_team_with_owner_member):
    client = Client()
    team = sample_team_with_owner_member.team

    team.key = number_to_random_token(team.id)
    team.save()

    BillingPlan.objects.create(
        key="delete_project_plan",
        name="Delete Project Plan",
        max_projects=10,
        max_products=10,
        max_components=10
    )
    team.billing_plan = "delete_project_plan"
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["user_teams"] = {
        team.key: {"role": "owner", "name": team.name}
    }
    session["current_team"] = {
        "key": team.key,
        "role": "owner",
        "name": team.name
    }
    session.save()

    # Create project
    response = client.post(
        reverse("sboms:projects_dashboard"),
        {"name": "Test Project"}
    )
    assert response.status_code == 302

    # Delete project
    project_id = Project.objects.first().id
    response = client.get(
        reverse("sboms:delete_project", kwargs={"project_id": project_id})
    )
    assert response.status_code == 302

    # Verify project is deleted
    assert not Project.objects.filter(pk=project_id).exists()

    # Check success messages
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 2
    assert str(messages[0]) == "Project Test Project created"
    assert str(messages[1]) == "Project Test Project deleted"


@pytest.mark.django_db
def test_create_component(sample_team_with_owner_member):
    client = Client()
    team = sample_team_with_owner_member.team

    team.key = number_to_random_token(team.id)
    team.save()

    BillingPlan.objects.create(
        key="default_plan",
        name="Default Plan",
        max_components=10,
        max_products=10,
        max_projects=10
    )
    team.billing_plan = "default_plan"
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["current_team"] = {"id": team.id, "role": "owner", "key": team.key}
    session.save()

    response = client.post(
        reverse("sboms:components_dashboard"),
        {"name": "Test Component"}
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_create_duplicate_component(sample_team_with_owner_member):  # Changed fixture
    client = Client()
    team = sample_team_with_owner_member.team

    # Setup billing plan
    BillingPlan.objects.create(
        key="duplicate_test_plan",
        name="Duplicate Test Plan",
        max_components=10,
        max_products=10,
        max_projects=10
    )
    team.billing_plan = "duplicate_test_plan"
    team.key = number_to_random_token(team.id)
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["current_team"] = {
        "id": team.id,
        "role": "owner",
        "key": team.key
    }
    session.save()

    # Create first component
    response = client.post(
        reverse("sboms:components_dashboard"),
        {"name": "Test Component"}
    )
    assert response.status_code == 302

    # Try to create duplicate component
    response = client.post(
        reverse("sboms:components_dashboard"),
        {"name": "Test Component"}
    )
    assert response.status_code == 200  # Form is re-rendered
    content = response.content.decode()
    assert "A component with this name already exists in this team" in content

    # Verify only one component exists
    count = Component.objects.filter(team=team, name="Test Component").count()
    assert count == 1


@pytest.mark.django_db
def test_delete_component(sample_team_with_owner_member):
    client = Client()
    team = sample_team_with_owner_member.team

    team.key = number_to_random_token(team.id)
    team.save()

    BillingPlan.objects.create(
        key="delete_component_plan",
        name="Delete Component Plan",
        max_components=10,
        max_products=10,
        max_projects=10
    )
    team.billing_plan = "delete_component_plan"
    team.save()

    client.force_login(team.members.first())
    session = client.session
    session["user_teams"] = {
        team.key: {"role": "owner", "name": team.name}
    }
    session["current_team"] = {
        "key": team.key,
        "role": "owner",
        "name": team.name
    }
    session.save()

    # Create component
    response = client.post(
        reverse("sboms:components_dashboard"),
        {"name": "Test Component"}
    )
    assert response.status_code == 302

    # Delete component
    component_id = Component.objects.first().id
    response = client.get(
        reverse("sboms:delete_component", kwargs={"component_id": component_id})
    )
    assert response.status_code == 302

    # Verify component is deleted
    assert not Component.objects.filter(pk=component_id).exists()

    # Check success messages
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 2
    assert str(messages[0]) == "Component Test Component created"
    assert str(messages[1]) == "Component Test Component deleted"


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
def test_adding_and_removing_components_to_projects(
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test adding and removing components to/from projects."""
    client = Client()

    uri = reverse("sboms:project_details", kwargs={"project_id": sample_project.id})

    # Set up session with team access
    setup_test_session(client, sample_project.team, sample_project.team.members.first())

    # Test adding component
    response: HttpResponse = client.post(
        uri + "?action=add_components", {"component_" + sample_component.id: sample_component.id}
    )
    assert response.status_code == 302
    assert response.url == uri

    # Verify component was added
    sample_project.refresh_from_db()
    assert sample_component in sample_project.components.all()

    # Test removing component
    response = client.post(
        uri + "?action=remove_components", {"component_" + sample_component.id: sample_component.id}
    )
    assert response.status_code == 302
    assert response.url == uri

    # Verify component was removed
    sample_project.refresh_from_db()
    assert sample_component not in sample_project.components.all()


@pytest.mark.django_db
def test_adding_and_removing_projects_to_products(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
):
    """Test adding and removing projects to/from products."""
    client = Client()

    uri = reverse("sboms:product_details", kwargs={"product_id": sample_product.id})

    # Set up session with team access
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test adding project
    response: HttpResponse = client.post(
        uri + "?action=add_projects", {"project_" + sample_project.id: sample_project.id}
    )
    assert response.status_code == 302
    assert response.url == uri

    # Verify project was added
    sample_product.refresh_from_db()
    assert sample_project in sample_product.projects.all()

    # Test removing project
    response = client.post(
        uri + "?action=remove_projects", {"project_" + sample_project.id: sample_project.id}
    )
    assert response.status_code == 302
    assert response.url == uri

    # Verify project was removed
    sample_product.refresh_from_db()
    assert sample_project not in sample_product.projects.all()


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
class TestDuplicateNames:
    """Test handling of duplicate names for products, projects, and components."""

    def test_create_duplicate_product_name(self, client, sample_team_with_owner_member, caplog):
        """Test that creating a product with a duplicate name in the same team fails gracefully."""
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="duplicate_prod_plan",
            name="Duplicate Product Plan",
            max_products=10,
            max_projects=10,
            max_components=10
        )
        team.billing_plan = "duplicate_prod_plan"
        team.key = number_to_random_token(team.id)
        team.save()

        client.force_login(team.members.first())
        session = client.session
        session["current_team"] = {"id": team.id, "role": "owner", "key": team.key}
        session.save()

        # Create first product
        _ = Product.objects.create(
            name="Product 1",
            team=team
        )

        # Try to create second product with same name
        response = client.post(
            reverse("sboms:products_dashboard"),
            data={"name": "Product 1"}
        )

        assert response.status_code == 200  # Form is re-rendered
        content = response.content.decode()
        assert "A product with this name already exists in this team" in content

        # Verify only one product exists
        count = Product.objects.filter(team=team, name="Product 1").count()
        assert count == 1

    def test_create_duplicate_project_name(self, client, sample_team_with_owner_member, caplog):
        """Test that creating a project with a duplicate name in the same team fails gracefully."""
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="duplicate_proj_plan",
            name="Duplicate Project Plan",
            max_projects=10,
            max_products=10,
            max_components=10
        )
        team.billing_plan = "duplicate_proj_plan"
        team.key = number_to_random_token(team.id)
        team.save()

        client.force_login(team.members.first())
        session = client.session
        session["current_team"] = {"id": team.id, "role": "owner", "key": team.key}
        session.save()

        # Create first project
        _ = Project.objects.create(
            name="Project 1",
            team=team
        )

        # Try to create second project with same name
        response = client.post(
            reverse("sboms:projects_dashboard"),
            data={"name": "Project 1"}
        )

        assert response.status_code == 200  # Form is re-rendered
        content = response.content.decode()
        assert "A project with this name already exists in this team" in content

        # Verify only one project exists
        count = Project.objects.filter(team=team, name="Project 1").count()
        assert count == 1

    def test_create_duplicate_component_name(self, client, sample_team_with_owner_member, caplog):
        """Test that creating a component with a duplicate name in the same team fails gracefully."""
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="duplicate_comp_plan",
            name="Duplicate Component Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "duplicate_comp_plan"
        team.key = number_to_random_token(team.id)
        team.save()

        client.force_login(team.members.first())
        session = client.session
        session["current_team"] = {"id": team.id, "role": "owner", "key": team.key}
        session.save()

        # Create first component
        _ = Component.objects.create(
            name="Component 1",
            team=team
        )

        # Try to create second component with same name
        response = client.post(
            reverse("sboms:components_dashboard"),
            data={"name": "Component 1"}
        )

        assert response.status_code == 200  # Form is re-rendered
        content = response.content.decode()
        assert "A component with this name already exists in this team" in content

        # Verify only one component exists
        count = Component.objects.filter(team=team, name="Component 1").count()
        assert count == 1


@pytest.mark.django_db
class TestBillingPlanLimits:
    """Test billing plan enforcement for resource creation limits."""

    def _setup_team_plan(self, client, team, plan_data):
        """Helper to configure team billing plan and session."""
        plan = BillingPlan.objects.create(**plan_data)
        team.billing_plan = plan.key
        # Set valid team key that encodes the team ID
        team.key = number_to_random_token(team.id)
        team.save()

        client.force_login(team.members.first())
        session = client.session
        session["current_team"] = {
            "id": team.id,
            "role": "owner",
            "key": team.key  # This key will properly encode the team ID
        }
        session.save()
        return plan

    def test_product_creation_limits(self, client, sample_team_with_owner_member):
        """Test product creation with billing limits."""
        plan = self._setup_team_plan(
            client,
            sample_team_with_owner_member.team,
            {
                "key": "test_prod_plan",
                "name": "Product Limit Plan",
                "max_products": 2,
                "max_projects": 10,
                "max_components": 10
            }
        )

        # Create up to limit
        for i in range(plan.max_products):
            response = client.post(
                reverse("sboms:products_dashboard"),
                {"name": f"Product {i+1}"}
            )
            assert response.status_code == 302

        # Try to exceed limit
        response = client.post(
            reverse("sboms:products_dashboard"),
            {"name": "Over Limit Product"}
        )
        assert response.status_code == 403
        assert f"maximum {plan.max_products} products" in response.content.decode()

    def test_project_creation_limits(self, client, sample_team_with_owner_member):
        """Test project creation with billing limits."""
        plan = self._setup_team_plan(
            client,
            sample_team_with_owner_member.team,
            {
                "key": "test_proj_plan",
                "name": "Project Limit Plan",
                "max_projects": 1,
                "max_products": 10,
                "max_components": 10
            }
        )

        # Create up to limit
        response = client.post(
            reverse("sboms:projects_dashboard"),
            {"name": "Project 1"}
        )
        assert response.status_code == 302

        # Try to exceed limit
        response = client.post(
            reverse("sboms:projects_dashboard"),
            {"name": "Over Limit Project"}
        )
        assert response.status_code == 403
        assert f"maximum {plan.max_projects} projects" in response.content.decode()

    def test_component_creation_limits(self, client, sample_team_with_owner_member):
        """Test component creation with billing limits."""
        plan = self._setup_team_plan(
            client,
            sample_team_with_owner_member.team,
            {
                "key": "test_comp_plan",
                "name": "Component Limit Plan",
                "max_components": 3,
                "max_products": 10,
                "max_projects": 10
            }
        )

        # Create up to limit
        for i in range(plan.max_components):
            response = client.post(
                reverse("sboms:components_dashboard"),
                {"name": f"Component {i+1}"}
            )
            assert response.status_code == 302

        # Try to exceed limit
        response = client.post(
            reverse("sboms:components_dashboard"),
            {"name": "Over Limit Component"}
        )
        assert response.status_code == 403
        assert f"maximum {plan.max_components} components" in response.content.decode()

    def test_unlimited_plan_allows_creation(self, client, sample_team_with_owner_member):
        """Test unlimited plan allows creation beyond default limits."""
        self._setup_team_plan(
            client,
            sample_team_with_owner_member.team,
            {
                "key": "unlimited",
                "name": "Unlimited Plan",
                "max_products": None,
                "max_projects": None,
                "max_components": None
            }
        )

        # Create multiple resources
        for i in range(5):
            client.post(reverse("sboms:products_dashboard"), {"name": f"Product {i+1}"})
            client.post(reverse("sboms:projects_dashboard"), {"name": f"Project {i+1}"})
            client.post(reverse("sboms:components_dashboard"), {"name": f"Component {i+1}"})

        assert Product.objects.count() == 5
        assert Project.objects.count() == 5
        assert Component.objects.count() == 5

    def test_no_plan_blocks_creation(self, client, sample_team_with_owner_member):
        """Test resource creation fails when no billing plan exists."""
        team = sample_team_with_owner_member.team
        team.billing_plan = None
        team.key = number_to_random_token(team.id)
        team.save()

        client.force_login(team.members.first())
        session = client.session
        session["current_team"] = {
            "id": team.id,
            "role": "owner",
            "key": team.key
        }
        session.save()

        # Test product creation
        response = client.post(
            reverse("sboms:products_dashboard"),
            {"name": "Test Product"}
        )
        assert response.status_code == 403
        assert "No active billing plan" in response.content.decode()

        # Test project creation
        response = client.post(
            reverse("sboms:projects_dashboard"),
            {"name": "Test Project"}
        )
        assert response.status_code == 403

        # Test component creation
        response = client.post(
            reverse("sboms:components_dashboard"),
            {"name": "Test Component"}
        )
        assert response.status_code == 403
