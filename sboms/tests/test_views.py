from __future__ import annotations

import os
from urllib.parse import quote

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from core.fixtures import sample_user  # noqa: F401
from teams.models import Member

from ..models import SBOM, Component, Product, Project
from .fixtures import (
    sample_access_token,  # noqa: F401
    sample_component,  # noqa: F401
    sample_project,  # noqa: F401
    sample_sbom,  # noqa: F401
)


@pytest.mark.django_db
def test_dasbhoard_pages_only_accessible_when_logged_in(sample_user):  # noqa: F811
    """Test that dashboard pages require authentication."""
    uris = [
        reverse("sboms:products_dashboard"),
        reverse("sboms:projects_dashboard"),
        reverse("sboms:components_dashboard"),
    ]

    client = Client()

    for uri in uris:
        response: HttpResponse = client.get(uri)

        assert response.status_code == 302
        assert quote(response.request["PATH_INFO"]) == uri

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    for uri in uris:
        response: HttpResponse = client.get(uri)

        assert response.status_code == 200
        assert quote(response.request["PATH_INFO"]) == uri


@pytest.mark.django_db
def test_create_product(sample_user):  # noqa: F811
    client = Client()

    uri = reverse("sboms:products_dashboard")

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.post(uri, {"name": "Test Product"})

    assert response.status_code == 302
    assert response.url == reverse("sboms:products_dashboard")

    messages = list(response.wsgi_request._messages)
    assert len(messages) == 1
    assert str(messages[0]) == "Product Test Product created"


@pytest.mark.django_db
def test_delete_product(sample_user):  # noqa: F811
    client = Client()

    uri = reverse("sboms:products_dashboard")

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.post(uri, {"name": "Test Product"})
    assert response.status_code == 302
    assert response.url == reverse("sboms:products_dashboard")

    product_id = Product.objects.first().id

    uri = reverse("sboms:delete_product", kwargs={"product_id": product_id})

    response: HttpResponse = client.get(uri)

    assert response.status_code == 302

    messages = list(response.wsgi_request._messages)
    assert len(messages) == 2
    assert str(messages[0]) == "Product Test Product created"
    assert str(messages[1]) == "Product Test Product deleted"

    assert Product.objects.filter(id=product_id).exists() is False


@pytest.mark.django_db
def test_create_project(sample_user):  # noqa: F811
    client = Client()

    uri = reverse("sboms:projects_dashboard")

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.post(uri, {"name": "Test Project"})
    assert response.status_code == 302
    assert response.url == reverse("sboms:projects_dashboard")

    messages = list(response.wsgi_request._messages)
    assert len(messages) == 1
    assert str(messages[0]) == "Project Test Project created"


@pytest.mark.django_db
def test_delete_project(sample_user):  # noqa: F811
    client = Client()

    uri = reverse("sboms:projects_dashboard")

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.post(uri, {"name": "Test Project"})
    assert response.status_code == 302
    assert response.url == reverse("sboms:projects_dashboard")

    project_id = Project.objects.first().id

    uri = reverse("sboms:delete_project", kwargs={"project_id": project_id})

    response: HttpResponse = client.get(uri)

    assert response.status_code == 302

    messages = list(response.wsgi_request._messages)
    assert len(messages) == 2
    assert str(messages[0]) == "Project Test Project created"
    assert str(messages[1]) == "Project Test Project deleted"

    assert Project.objects.filter(id=project_id).exists() is False


@pytest.mark.django_db
def test_create_component(sample_user):  # noqa: F811
    client = Client()

    uri = reverse("sboms:components_dashboard")

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.post(uri, {"name": "Test Component"})

    assert response.status_code == 302
    assert response.url == reverse("sboms:components_dashboard")

    messages = list(response.wsgi_request._messages)
    assert len(messages) == 1
    assert str(messages[0]) == "Component Test Component created"


@pytest.mark.django_db
def test_create_duplicate_component(sample_user):  # noqa: F811
    client = Client()

    uri = reverse("sboms:components_dashboard")

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    # Create first component
    response: HttpResponse = client.post(uri, {"name": "Test Component"})
    assert response.status_code == 302
    assert response.url == reverse("sboms:components_dashboard")

    messages = list(response.wsgi_request._messages)
    assert len(messages) == 1
    assert str(messages[0]) == "Component Test Component created"

    # Try to create duplicate component
    response: HttpResponse = client.post(uri, {"name": "Test Component"})
    assert response.status_code == 200  # Form is re-rendered
    content = response.content.decode()
    assert "A component with this name already exists in this team" in content

    # Verify only one component was created
    assert Component.objects.filter(name="Test Component").count() == 1


@pytest.mark.django_db
def test_delete_component(sample_user):  # noqa: F811
    client = Client()

    uri = reverse("sboms:components_dashboard")

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.post(uri, {"name": "Test Component"})

    assert response.status_code == 302
    assert response.url == reverse("sboms:components_dashboard")

    component_id = Component.objects.first().id

    uri = reverse("sboms:delete_component", kwargs={"component_id": component_id})

    response: HttpResponse = client.get(uri)

    assert response.status_code == 302

    messages = list(response.wsgi_request._messages)
    assert len(messages) == 2
    assert str(messages[0]) == "Component Test Component created"
    assert str(messages[1]) == "Component Test Component deleted"

    assert Component.objects.filter(id=component_id).exists() is False


@pytest.mark.django_db
def test_details_page_only_accessible_when_logged_in(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
):
    uris = [
        reverse("sboms:product_details", kwargs={"product_id": sample_product.id}),
        reverse("sboms:project_details", kwargs={"project_id": sample_project.id}),
        reverse("sboms:component_details", kwargs={"component_id": sample_component.id}),
        reverse("sboms:sbom_details", kwargs={"sbom_id": sample_sbom.id}),
    ]

    client = Client()

    for uri in uris:
        response: HttpResponse = client.get(uri)

        assert response.status_code == 302
        assert quote(response.request["PATH_INFO"]) == uri

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

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
    mocker.patch("boto3.resource")
    mocked_s3_get_file_data = mocker.patch("core.object_store.S3Client.get_file_data")
    mocked_s3_get_file_data.return_value = b'{"name": "com.github.test/test", "a": 1}'

    client = Client()

    uri = reverse("sboms:sbom_download", kwargs={"sbom_id": sample_sbom.id})

    response: HttpResponse = client.get(uri)

    assert response.status_code == 403

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.get(uri)

    assert response.status_code == 200
    assert quote(response.request["PATH_INFO"]) == uri
    assert response.json()["name"] == "com.github.test/test"


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
    # By default sample component beloings to default team that's created for sample_user upon user creation.
    client = Client()

    uri = reverse("sboms:transfer_component", kwargs={"component_id": sample_component.id})

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.post(uri, {"team_key": sample_team_with_owner_member.team.key})

    assert response.status_code == 302
    assert response.url == reverse(
        "sboms:component_details",
        kwargs={"component_id": sample_component.id},
    )

    sample_component.refresh_from_db()
    assert sample_component.team_id == sample_team_with_owner_member.team_id


@pytest.mark.django_db
def test_adding_and_removing_components_to_projects(
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    client = Client()

    uri = reverse("sboms:project_details", kwargs={"project_id": sample_project.id})

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.post(
        uri + "?action=add_components", {"component_" + sample_component.id: sample_component.id}
    )

    assert response.status_code == 200

    sample_project.refresh_from_db()
    assert sample_project.components.count() == 1
    assert sample_project.components.first().id == sample_component.id

    response: HttpResponse = client.post(
        uri + "?action=remove_components", {"component_" + sample_component.id: sample_component.id}
    )

    assert response.status_code == 200

    sample_project.refresh_from_db()
    assert sample_project.components.count() == 0


@pytest.mark.django_db
def test_adding_and_removing_projects_to_products(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
):
    client = Client()

    uri = reverse("sboms:product_details", kwargs={"product_id": sample_product.id})

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.post(
        uri + "?action=add_projects", {"project_" + sample_project.id: sample_project.id}
    )

    assert response.status_code == 200

    sample_product.refresh_from_db()
    assert sample_product.projects.count() == 1
    assert sample_product.projects.first().id == sample_project.id

    response: HttpResponse = client.post(
        uri + "?action=remove_projects", {"project_" + sample_project.id: sample_project.id}
    )

    assert response.status_code == 200

    sample_product.refresh_from_db()
    assert sample_product.projects.count() == 0


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
        client.force_login(sample_team_with_owner_member.user)
        team = sample_team_with_owner_member.team
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
        client.force_login(sample_team_with_owner_member.user)
        team = sample_team_with_owner_member.team
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
        client.force_login(sample_team_with_owner_member.user)
        team = sample_team_with_owner_member.team
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
