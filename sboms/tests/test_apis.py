from __future__ import annotations

import json
import os
import pathlib

import pytest
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from access_tokens.models import AccessToken
from billing.models import BillingPlan
from core.tests.fixtures import sample_user  # noqa: F401
from teams.fixtures import sample_team_with_owner_member  # noqa: F401
from teams.models import Member

from catalog.models import Component, Product, Project
from ..models import SBOM
from .fixtures import (  # noqa: F401
    sample_access_token,
    sample_component,
    sample_project,
    sample_sbom,
)
from .test_views import setup_test_session


@pytest.mark.django_db
def test_sbom_api_is_public(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
):
    client = Client()

    unknown_uri = reverse(
        "api-1:get_item_public_status",
        kwargs={"item_type": "unknown", "item_id": "random"},
    )

    component_uri = reverse(
        "api-1:get_item_public_status",
        kwargs={"item_type": "component", "item_id": sample_sbom.component.id},
    )

    project_uri = reverse(
        "api-1:get_item_public_status",
        kwargs={"item_type": "project", "item_id": sample_project.id},
    )

    product_uri = reverse(
        "api-1:get_item_public_status",
        kwargs={"item_type": "product", "item_id": sample_product.id},
    )

    # Set up session with team access
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Test for unknown type
    response: HttpResponse = client.get(unknown_uri, content_type="application/json")
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid item type"

    # Make the component public
    response = client.patch(component_uri, json.dumps({"is_public": True}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Verify component is public
    response = client.get(component_uri, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Make the project public
    response = client.patch(project_uri, json.dumps({"is_public": True}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Verify project is public
    response = client.get(project_uri, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Make the product public
    response = client.patch(product_uri, json.dumps({"is_public": True}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Verify product is public
    response = client.get(product_uri, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True


@pytest.mark.django_db
def test_sbom_api_get_user_items(
    sample_user: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    client = Client()

    uri = reverse("api-1:get_user_items", kwargs={"item_type": "product"})

    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])

    response: HttpResponse = client.get(
        uri, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}"
    )

    assert response.status_code == 200
    result = response.json()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["item_key"] == sample_product.id
    assert result[0]["item_name"] == sample_product.name

    uri = reverse("api-1:get_user_items", kwargs={"item_type": "project"})
    response: HttpResponse = client.get(
        uri, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}"
    )

    assert response.status_code == 200
    result = response.json()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["item_key"] == sample_project.id
    assert result[0]["item_name"] == sample_project.name

    uri = reverse("api-1:get_user_items", kwargs={"item_type": "component"})
    response: HttpResponse = client.get(
        uri, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}"
    )

    assert response.status_code == 200
    result = response.json()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["item_key"] == sample_component.id
    assert result[0]["item_name"] == sample_component.name


@pytest.mark.django_db
def test_sbom_upload_api_spdx(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    mocker.patch("boto3.resource")
    patched_upload_data_as_file = mocker.patch("core.object_store.S3Client.upload_data_as_file")
    SBOM.objects.all().delete()

    test_file_path = pathlib.Path(__file__).parent.resolve() / "test_data/sbomify_trivy.spdx.json"
    sbom_data = open(test_file_path, "r").read()

    client = Client()

    url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=sbom_data,
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    # Assert the response status code and data
    assert response.status_code == 201
    assert "id" in response.json()

    # Verify sbom was uploaded against the default team for the user
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.component.id == sample_component.id
    assert sbom.sbom_filename == "7a09e41d16c74019cecf78bc61682eafe1147d0d086fae04d562a7eb3b40d623.json"
    assert patched_upload_data_as_file.call_count == 1

    assert SBOM.objects.count() == 1


@pytest.mark.django_db
def test_sbom_upload_api_cyclonedx(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    mocker.patch("boto3.resource")
    patched_upload_data_as_file = mocker.patch("core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    test_file_path = pathlib.Path(__file__).parent.resolve() / "test_data/sbomify_trivy.cdx.json"
    sbom_data = open(test_file_path, "r").read()

    client = Client()

    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=sbom_data,
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    # Assert the response status code and data
    assert response.status_code == 201
    assert "id" in response.json()

    # Verify sbom was uploaded against the default team for the user
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.component.id == sample_component.id
    assert sbom.sbom_filename == "895d8ac5dfda0ce06fca501e1e5a72708bb1af62c3d080f23193588d6e63556e.json"
    assert sbom.format == "cyclonedx"
    assert sbom.format_version == "1.6"
    assert sbom.version == ""
    assert patched_upload_data_as_file.call_count == 1

    assert SBOM.objects.count() == 1


@pytest.mark.django_db
def test_get_and_set_component_metadata(sample_component: Component, sample_access_token: AccessToken):  # noqa: F811
    client = Client()

    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})

    # Get unset metadata
    response = client.get(
        url,
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 200
    response_json = response.json()

    assert response_json["id"] == sample_component.id
    assert response_json["name"] == sample_component.name
    assert response_json["supplier"] == {"contacts": []}
    assert response_json["authors"] == []
    assert response_json["licenses"] == []
    assert len(response_json.keys()) == 5

    # Set component metadata
    component_metadata = {
        "supplier": {
            "name": "Test supplier",
            "url": ["http://supply.org"],
            "address": "1234, Test Street, Test City, Test Country",
            "contacts": [{"name": "C1", "email": "c1@contacts.org", "phone": "2356236236"}],
        },
        "authors": [
            {"name": "A1", "email": "a1@example.org", "phone": "2356235"},
            {"name": "A2", "email": "a2@example.com", "phone": ""},
        ],
        "licenses": ["GPL-1.0", {"name": "custom", "url": "https://custom.com/license", "text": "Custom license text"}],
        "lifecycle_phase": "post-build",
    }

    response = client.patch(
        url,
        json.dumps(component_metadata),
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 204

    # Get metadata again and verify it was set
    response = client.get(
        url,
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["id"] == sample_component.id
    assert response_data["name"] == sample_component.name
    assert response_data["supplier"] == component_metadata["supplier"]
    assert response_data["supplier"]["contacts"] == component_metadata["supplier"]["contacts"]
    assert response_data["authors"] == component_metadata["authors"]
    assert response_data["lifecycle_phase"] == component_metadata["lifecycle_phase"]
    assert len(response_data["licenses"]) == 2
    assert response_data["licenses"][0] == "GPL-1.0"
    assert response_data["licenses"][1]["name"] == "custom"
    assert response_data["licenses"][1]["url"] == "https://custom.com/license"
    assert response_data["licenses"][1]["text"] == "Custom license text"


@pytest.mark.django_db
def test_component_copy_metadata_api(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    client = Client()

    # Create another component and set its metadata
    another_component = Component.objects.create(
        name="Another Component",
        team_id=sample_component.team_id,
        metadata={
            "supplier": {
                "name": "Another supplier",
                "url": ["http://another-supply.org"],
                "address": "5678, Another Street, Another City, Another Country",
                "contacts": [{"name": "C2", "email": "c2@contacts.org", "phone": "1234567890"}],
            },
            "authors": [
                {"name": "B1", "email": "b1@example.org", "phone": "9876543210"},
                {"name": "B2", "email": "b2@example.com", "phone": ""},
            ],
            "licenses": ["MIT"],
            "lifecycle_phase": "development",
        },
    )

    url = reverse("api-1:copy_component_metadata")
    payload = {
        "source_component_id": another_component.id,
        "target_component_id": sample_component.id,
    }

    # Call the '/sboms/component/copy-meta' API endpoint via HTTP PUT request
    response = client.put(
        url,
        json.dumps(payload),
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 204

    # Verify that sample_component's metadata has been set
    sample_component.refresh_from_db()
    assert sample_component.metadata["supplier"]["name"] == "Another supplier"
    assert sample_component.metadata["supplier"]["url"] == ["http://another-supply.org"]
    assert sample_component.metadata["supplier"]["contacts"][0]["name"] == "C2"
    assert sample_component.metadata["authors"][0]["name"] == "B1"
    assert sample_component.metadata["licenses"][0] == "MIT"
    assert sample_component.metadata["lifecycle_phase"] == "development"


@pytest.mark.django_db
def test_metadata_enrichment(sample_component: Component, sample_access_token: AccessToken):  # noqa: F811
    client = Client()

    component_metadata = {
        "supplier": {
            "name": "Test supplier",
            "url": ["http://supply.org"],
            "address": "1234, Test Street, Test City, Test Country",
            "contacts": [{"name": "C1", "email": "c1@contacts.org", "phone": "2356236236"}],
        },
        "authors": [
            {"name": "A1", "email": "a1@example.org", "phone": "2356235"},
            {"name": "A2", "email": "a2@example.com", "phone": ""},
        ],
        "licenses": ["GPL-1.0"],
        "lifecycle_phase": "post-build",
    }

    sample_component.metadata = component_metadata
    sample_component.save()

    sbom_metadata = {
        "timestamp": "2024-05-31T13:08:16Z",
        "tools": {"components": [{"type": "application", "author": "anchore", "name": "syft", "version": "1.5.0"}]},
        "component": {
            "bom-ref": "47c818a1c684e4e2",
            "type": "container",
            "name": "alpine",
            "version": "sha256:dac15f325cac528994a5efe78787cd03bdd796979bda52fdd81cf6242db7197f",
        },
        "licenses": [{"license": {"id": "GPL-2.0-only"}}],
    }

    url = reverse(
        "api-1:get_cyclonedx_component_metadata", kwargs={"spec_version": "1.5", "component_id": sample_component.id}
    )

    # Get unset metadata
    response = client.post(
        url,
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
        data=json.dumps(sbom_metadata),
    )

    assert response.status_code == 200

    response_json = response.json()

    assert response_json["supplier"]["name"] == component_metadata["supplier"]["name"]
    assert response_json["supplier"]["url"][0] == component_metadata["supplier"]["url"][0]
    assert "address" not in response_json["supplier"]  # cyclonedx 1.5 does not have address field
    assert "contact" in response_json["supplier"]

    assert response_json["authors"][0]["name"] == component_metadata["authors"][0]["name"]
    assert response_json["authors"][0]["email"] == component_metadata["authors"][0]["email"]
    assert response_json["authors"][0]["phone"] == component_metadata["authors"][0]["phone"]

    assert response_json["authors"][1]["name"] == component_metadata["authors"][1]["name"]
    assert response_json["authors"][1]["email"] == component_metadata["authors"][1]["email"]
    # Verify enrichment does not set empty fields
    assert "phone" not in response_json["authors"][1]

    assert response_json["timestamp"] == sbom_metadata["timestamp"]
    assert response_json["component"]["bom-ref"] == sbom_metadata["component"]["bom-ref"]
    assert response_json["component"]["type"] == sbom_metadata["component"]["type"]
    assert response_json["component"]["name"] == sbom_metadata["component"]["name"]
    assert response_json["component"]["version"] == sbom_metadata["component"]["version"]

    # Verify license field is not overridden
    assert response_json["licenses"][0]["license"]["id"] == sbom_metadata["licenses"][0]["license"]["id"]

    # Test overrides
    # For this we need to have fields that are present in both sbom and component metadata
    response = client.post(
        url + "?override_metadata=true&sbom_version=1.1.1&override_name=true",
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
        data=json.dumps(sbom_metadata),
    )

    assert response.status_code == 200

    response_json = response.json()

    assert response_json["supplier"]["name"] == component_metadata["supplier"]["name"]

    assert response_json["authors"][0]["name"] == component_metadata["authors"][0]["name"]

    # Verify license field is overridden
    assert response_json["licenses"][0]["id"] == component_metadata["licenses"][0]

    # Verify version is overridden
    assert response_json["component"]["version"] == "1.1.1"

    # Verify name is overridden
    assert response_json["component"]["name"] == sample_component.name

    # Test override version for cdx 1.5 and 1.6. We've already tested 1.5, so we'll test 1.6 here
    url = reverse(
        "api-1:get_cyclonedx_component_metadata", kwargs={"spec_version": "1.6", "component_id": sample_component.id}
    )

    # Get unset metadata
    response = client.post(
        url + "?override_metadata=true&sbom_version=1.1.1&override_name=true",
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
        data=json.dumps(sbom_metadata),
    )

    assert response.status_code == 200
    response_json = response.json()
    # Verify version is overridden
    assert response_json["component"]["version"] == "1.1.1"


@pytest.mark.django_db
def test_metadata_enrichment_on_no_component_in_metadata(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    client = Client()

    component_metadata = {
        "supplier": {
            "name": "Test supplier",
            "url": ["http://supply.org"],
            "address": "1234, Test Street, Test City, Test Country",
            "contacts": [{"name": "C1", "email": "c1@contacts.org", "phone": "2356236236"}],
        },
        "authors": [
            {"name": "A1", "email": "a1@example.org", "phone": "2356235"},
            {"name": "A2", "email": "a2@example.com", "phone": ""},
        ],
        "licenses": ["GPL-1.0"],
        "lifecycle_phase": "post-build",
    }

    sample_component.metadata = component_metadata
    sample_component.save()

    sbom_metadata = {
        "timestamp": "2024-05-31T13:08:16Z",
        "tools": {"components": [{"type": "application", "author": "anchore", "name": "syft", "version": "1.5.0"}]},
        "licenses": [{"license": {"id": "GPL-2.0-only"}}],
    }

    url = reverse(
        "api-1:get_cyclonedx_component_metadata", kwargs={"spec_version": "1.6", "component_id": sample_component.id}
    )

    # Get unset metadata
    response = client.post(
        url + "?sbom_version=1.1.1&override_name=true",
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
        data=json.dumps(sbom_metadata),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing required 'component' field in SBOM metadata"


@pytest.mark.django_db
def test_get_dashboard_summary_unauthenticated(client: Client):
    """Test that an unauthenticated user receives a 403."""
    url = reverse("api-1:get_dashboard_summary")
    response = client.get(url, content_type="application/json")
    assert response.status_code == 403
    assert response.json()["detail"] == "Authentication required."


@pytest.mark.django_db
def test_get_dashboard_summary_authenticated_no_data(
    sample_user: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    client: Client,
):
    """Test that an authenticated user with no associated data gets an empty summary."""
    url = reverse("api-1:get_dashboard_summary")
    response = client.get(
        url,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_products"] == 0
    assert data["total_projects"] == 0
    assert data["total_components"] == 0
    assert data["latest_uploads"] == []


@pytest.mark.django_db
def test_get_dashboard_summary_authenticated_with_data(
    sample_user: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    client: Client,
    sample_team_with_owner_member,  # noqa: F811
):
    """Test that an authenticated user with data gets the correct summary."""
    # Ensure sample_sbom is associated with sample_component, which is part of the user's team
    sample_component.team = sample_team_with_owner_member.team
    sample_component.save()
    sample_sbom.component = sample_component
    sample_sbom.name = "Test SBOM 1"
    sample_sbom.version = "1.0"
    sample_sbom.save()

    # Create a second SBOM for the same component to test ordering and limit
    SBOM.objects.create(
        name="Test SBOM 2",
        version="2.0",
        component=sample_component,
        format="cyclonedx",  # ensure other fields are present
        sbom_filename="test2.json",
        source="test",
    )
    # Create another product, project, component under the same team
    # (assuming fixtures create them under some default or no team initially)
    Product.objects.create(name="Product 2", team=sample_team_with_owner_member.team)
    Project.objects.create(name="Project 2", team=sample_team_with_owner_member.team)
    Component.objects.create(name="Component 2", team=sample_team_with_owner_member.team)

    url = reverse("api-1:get_dashboard_summary")
    response = client.get(
        url,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 200
    data = response.json()

    assert data["total_products"] == Product.objects.filter(team=sample_team_with_owner_member.team).count()
    assert data["total_projects"] == Project.objects.filter(team=sample_team_with_owner_member.team).count()
    assert data["total_components"] == Component.objects.filter(team=sample_team_with_owner_member.team).count()

    assert len(data["latest_uploads"]) <= 5  # API returns max 5
    assert len(data["latest_uploads"]) > 0  # We created 2

    # Check the content of the first upload (should be the latest one, Test SBOM 2)
    latest_upload = data["latest_uploads"][0]
    assert latest_upload["component_name"] == sample_component.name
    assert latest_upload["sbom_name"] == "Test SBOM 2"
    assert latest_upload["sbom_version"] == "2.0"
    assert "created_at" in latest_upload

    # Check the content of the second upload (Test SBOM 1)
    if len(data["latest_uploads"]) > 1:
        second_latest_upload = data["latest_uploads"][1]
        assert second_latest_upload["component_name"] == sample_component.name
        assert second_latest_upload["sbom_name"] == "Test SBOM 1"
        assert second_latest_upload["sbom_version"] == "1.0"


@pytest.mark.django_db
def test_component_metadata_license_expressions(sample_component: Component, sample_access_token: AccessToken):  # noqa: F811
    """Test that the component metadata API accepts license expressions."""
    client = Client()

    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})

    # Test license expressions with operators
    component_metadata = {
        "supplier": {"contacts": []},
        "authors": [],
        "licenses": ["Apache-2.0 WITH Commons-Clause", "MIT OR GPL-3.0", "BSD-3-Clause"],
        "lifecycle_phase": "pre-build",
    }

    response = client.patch(
        url,
        json.dumps(component_metadata),
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 204

    # Get metadata and verify license expressions are preserved
    response = client.get(
        url,
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["id"] == sample_component.id
    assert response_data["name"] == sample_component.name
    assert len(response_data["licenses"]) == 3
    assert "Apache-2.0 WITH Commons-Clause" in response_data["licenses"]
    assert "MIT OR GPL-3.0" in response_data["licenses"]
    assert "BSD-3-Clause" in response_data["licenses"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_input,expected_output",
    [
        ("https://jdoe.org", ["https://jdoe.org"]),  # Single string should be converted to array
        (["https://jdoe.org"], ["https://jdoe.org"]),  # Array should remain array
        (["https://jdoe.org", "https://backup.org"], ["https://jdoe.org", "https://backup.org"]),  # Multiple URLs
    ],
)
def test_component_metadata_supplier_url_handling(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    url_input,
    expected_output,
):
    """Test that supplier URL handling works correctly for both string and array inputs."""
    client = Client()

    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})

    # Test with different URL input formats
    metadata_with_url = {
        "supplier": {
            "contacts": [{"name": "John Doe", "email": "jdoe@example.com", "phone": ""}],
            "name": "Foo Bar Inc",
            "url": url_input,
        },
        "authors": [],
        "licenses": ["Apache-2.0"],
        "lifecycle_phase": None,
    }

    response = client.patch(
        url,
        json.dumps(metadata_with_url),
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 204

    # Get metadata and verify URL was handled correctly
    response = client.get(
        url,
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["id"] == sample_component.id
    assert response_data["name"] == sample_component.name
    assert response_data["supplier"]["url"] == expected_output
    assert response_data["supplier"]["name"] == "Foo Bar Inc"
    assert len(response_data["supplier"]["contacts"]) == 1
    assert response_data["supplier"]["contacts"][0]["name"] == "John Doe"


@pytest.mark.django_db
def test_component_metadata_patch_partial_update(sample_component: Component, sample_access_token: AccessToken):  # noqa: F811
    """Test that PATCH only updates the fields that are provided."""
    client = Client()

    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})

    # First, set some initial metadata
    initial_metadata = {
        "supplier": {
            "name": "Initial Supplier",
            "url": ["https://initial.com"],
            "address": "123 Initial St",
            "contacts": [{"name": "Initial Contact", "email": "initial@example.com", "phone": "123-456-7890"}],
        },
        "authors": [{"name": "Initial Author", "email": "initial@example.com", "phone": "123-456-7890"}],
        "licenses": ["MIT"],
        "lifecycle_phase": "design",
    }

    response = client.patch(
        url,
        json.dumps(initial_metadata),
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )
    assert response.status_code == 204

    # Now, only update the lifecycle_phase using PATCH
    partial_update = {"lifecycle_phase": "build"}

    response = client.patch(
        url,
        json.dumps(partial_update),
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )
    assert response.status_code == 204

    # Verify that only lifecycle_phase was updated and other fields remain unchanged
    response = client.get(
        url,
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )
    assert response.status_code == 200
    response_data = response.json()

    # Verify lifecycle_phase was updated
    assert response_data["lifecycle_phase"] == "build"

    # Verify other fields remain unchanged
    assert response_data["supplier"]["name"] == "Initial Supplier"
    assert response_data["supplier"]["url"] == ["https://initial.com"]
    assert response_data["authors"][0]["name"] == "Initial Author"
    assert response_data["licenses"] == ["MIT"]


@pytest.mark.django_db
def test_component_metadata_author_information(sample_component: Component, sample_access_token: AccessToken):  # noqa: F811
    """Test that author information can be saved and retrieved correctly."""
    client = Client()

    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})

    # Test with complete author information
    metadata_with_authors = {
        "supplier": {"contacts": [], "name": None, "url": None, "address": None},
        "authors": [
            {"name": "John Doe", "email": "john@example.com", "phone": "123-456-7890"},
            {"name": "Jane Smith", "email": "jane@example.com", "phone": ""},  # Empty phone should work
            {"name": "Bob Wilson", "email": "", "phone": "987-654-3210"},  # Empty email should work
        ],
        "licenses": ["MIT"],
        "lifecycle_phase": None,
    }

    response = client.patch(
        url,
        json.dumps(metadata_with_authors),
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 204

    # Get metadata and verify authors were saved correctly
    response = client.get(
        url,
        content_type="application/json",
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["id"] == sample_component.id
    assert response_data["name"] == sample_component.name
    assert len(response_data["authors"]) == 3

    # Verify first author
    assert response_data["authors"][0]["name"] == "John Doe"
    assert response_data["authors"][0]["email"] == "john@example.com"
    assert response_data["authors"][0]["phone"] == "123-456-7890"

    # Verify second author (empty phone)
    assert response_data["authors"][1]["name"] == "Jane Smith"
    assert response_data["authors"][1]["email"] == "jane@example.com"
    assert "phone" not in response_data["authors"][1] or response_data["authors"][1]["phone"] == ""

    # Verify third author (empty email)
    assert response_data["authors"][2]["name"] == "Bob Wilson"
    assert "email" not in response_data["authors"][2] or response_data["authors"][2]["email"] == ""
    assert response_data["authors"][2]["phone"] == "987-654-3210"


@pytest.mark.django_db
def test_sbom_upload_file_cyclonedx(
    sample_user,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    mocker.patch("boto3.resource")
    patched_upload_data_as_file = mocker.patch("core.object_store.S3Client.upload_data_as_file")
    SBOM.objects.all().delete()

    test_file_path = pathlib.Path(__file__).parent.resolve() / "test_data/sbomify_trivy.cdx.json"

    client = Client()
    client.force_login(sample_user)

    url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id})

    with open(test_file_path, "rb") as f:
        response = client.post(url, data={"sbom_file": f}, format="multipart")

    # Assert the response status code and data
    assert response.status_code == 201
    assert "id" in response.json()

    # Verify SBOM was uploaded
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.component.id == sample_component.id
    assert sbom.format == "cyclonedx"
    assert sbom.source == "manual_upload"
    assert patched_upload_data_as_file.call_count == 1
    assert SBOM.objects.count() == 1


@pytest.mark.django_db
def test_sbom_upload_file_spdx(
    sample_user,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    mocker.patch("boto3.resource")
    patched_upload_data_as_file = mocker.patch("core.object_store.S3Client.upload_data_as_file")
    SBOM.objects.all().delete()

    test_file_path = pathlib.Path(__file__).parent.resolve() / "test_data/sbomify_trivy.spdx.json"

    client = Client()
    client.force_login(sample_user)

    url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id})

    with open(test_file_path, "rb") as f:
        response = client.post(url, data={"sbom_file": f}, format="multipart")

    # Assert the response status code and data
    assert response.status_code == 201
    assert "id" in response.json()

    # Verify SBOM was uploaded
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.component.id == sample_component.id
    assert sbom.format == "spdx"
    assert sbom.source == "manual_upload"
    assert patched_upload_data_as_file.call_count == 1
    assert SBOM.objects.count() == 1


@pytest.mark.django_db
def test_sbom_upload_file_invalid_format(
    sample_user,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    client = Client()
    client.force_login(sample_user)

    url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id})

    # Create a simple text file with invalid JSON
    from django.core.files.uploadedfile import SimpleUploadedFile

    invalid_file = SimpleUploadedFile("test.json", b"invalid json content", content_type="application/json")

    response = client.post(url, data={"sbom_file": invalid_file}, format="multipart")

    # Assert error response
    assert response.status_code == 400
    assert "Invalid JSON" in response.json()["detail"]


@pytest.mark.django_db
def test_sbom_upload_file_unauthorized(
    sample_component: Component,  # noqa: F811
):
    client = Client()
    # Don't log in user

    url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id})

    from django.core.files.uploadedfile import SimpleUploadedFile

    test_file = SimpleUploadedFile("test.json", b'{"test": "data"}', content_type="application/json")

    response = client.post(url, data={"sbom_file": test_file}, format="multipart")

    # Assert unauthorized response
    assert response.status_code == 401


@pytest.mark.django_db
def test_sbom_upload_file_too_large(
    sample_user,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    client = Client()
    client.force_login(sample_user)

    url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id})

    # Create a file that's too large (11MB)
    large_content = b"x" * (11 * 1024 * 1024)
    from django.core.files.uploadedfile import SimpleUploadedFile

    large_file = SimpleUploadedFile("large.json", large_content, content_type="application/json")

    response = client.post(url, data={"sbom_file": large_file}, format="multipart")

    # Assert error response
    assert response.status_code == 400
    assert "File size must be less than 10MB" in response.json()["detail"]


@pytest.mark.django_db
def test_delete_sbom_api(
    sample_access_token: AccessToken,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test SBOM deletion via API endpoint."""
    mocker.patch("boto3.resource")
    mock_delete_object = mocker.patch("core.object_store.S3Client.delete_object")

    client = Client()

    # Test unauthorized access (no token)
    url = reverse("api-1:delete_sbom", kwargs={"sbom_id": sample_sbom.id})
    response = client.delete(url)
    assert response.status_code == 401

    # Test with valid token and permissions
    response = client.delete(
        url,
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )

    assert response.status_code == 204
    assert SBOM.objects.filter(id=sample_sbom.id).count() == 0

    # Verify S3 file deletion was attempted
    mock_delete_object.assert_called_once()

    # Test deleting non-existent SBOM
    response = client.delete(
        url,
        headers={"Authorization": f"Bearer {sample_access_token.encoded_token}"},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_delete_sbom_api_forbidden(
    sample_sbom: SBOM,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test SBOM deletion with insufficient permissions."""
    mocker.patch("boto3.resource")

    # Create a different user and access token without permissions
    from django.contrib.auth import get_user_model

    from access_tokens.models import AccessToken
    from access_tokens.utils import create_personal_access_token

    User = get_user_model()
    other_user = User.objects.create_user(username="otheruser", password="password")
    token_str = create_personal_access_token(other_user)
    other_token = AccessToken.objects.create(user=other_user, encoded_token=token_str, description="Test Token")

    client = Client()
    url = reverse("api-1:delete_sbom", kwargs={"sbom_id": sample_sbom.id})

    response = client.delete(
        url,
        headers={"Authorization": f"Bearer {other_token.encoded_token}"},
    )

    assert response.status_code == 403
    assert SBOM.objects.filter(id=sample_sbom.id).count() == 1  # SBOM should still exist


@pytest.mark.django_db
def test_get_dashboard_summary_with_product_filter(
    sample_user: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_team_with_owner_member,  # noqa: F811
    client: Client,
):
    """Test that product filtering works correctly in dashboard summary."""
    from catalog.models import Component, Product, ProductProject, Project, ProjectComponent
    from sboms.models import SBOM

    team = sample_team_with_owner_member.team

    # Create test data
    # Product 1 with 2 projects and 3 components
    product1 = Product.objects.create(name="Product 1", team=team)
    project1a = Project.objects.create(name="Project 1A", team=team)
    project1b = Project.objects.create(name="Project 1B", team=team)
    component1a = Component.objects.create(name="Component 1A", team=team)
    component1b = Component.objects.create(name="Component 1B", team=team)
    component1c = Component.objects.create(name="Component 1C", team=team)

    # Link product to projects
    ProductProject.objects.create(product=product1, project=project1a)
    ProductProject.objects.create(product=product1, project=project1b)

    # Link projects to components
    ProjectComponent.objects.create(project=project1a, component=component1a)
    ProjectComponent.objects.create(project=project1a, component=component1b)
    ProjectComponent.objects.create(project=project1b, component=component1c)

    # Product 2 with 1 project and 1 component (should be excluded from filtered results)
    product2 = Product.objects.create(name="Product 2", team=team)
    project2 = Project.objects.create(name="Project 2", team=team)
    component2 = Component.objects.create(name="Component 2", team=team)
    ProductProject.objects.create(product=product2, project=project2)
    ProjectComponent.objects.create(project=project2, component=component2)

    # Create an SBOM for one of the components in product1
    SBOM.objects.create(
        name="Test SBOM",
        version="1.0",
        component=component1a,
        format="cyclonedx",
        sbom_filename="test.json",
        source="test",
    )

    url = reverse("api-1:get_dashboard_summary")
    response = client.get(
        f"{url}?product_id={product1.id}",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 200
    data = response.json()

    # Should show projects and components within product1 only
    assert data["total_products"] == 1  # Just the queried product
    assert data["total_projects"] == 2  # project1a, project1b
    assert data["total_components"] == 3  # component1a, component1b, component1c
    assert len(data["latest_uploads"]) == 1  # Only SBOM from product1


@pytest.mark.django_db
def test_get_dashboard_summary_with_project_filter(
    sample_user: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_team_with_owner_member,  # noqa: F811
    client: Client,
):
    """Test that project filtering works correctly in dashboard summary."""
    from catalog.models import Component, Project, ProjectComponent
    from sboms.models import SBOM

    team = sample_team_with_owner_member.team

    # Create test data
    project1 = Project.objects.create(name="Project 1", team=team)
    project2 = Project.objects.create(name="Project 2", team=team)

    # Project 1 has 2 components
    component1a = Component.objects.create(name="Component 1A", team=team)
    component1b = Component.objects.create(name="Component 1B", team=team)
    ProjectComponent.objects.create(project=project1, component=component1a)
    ProjectComponent.objects.create(project=project1, component=component1b)

    # Project 2 has 1 component (should be excluded from filtered results)
    component2 = Component.objects.create(name="Component 2", team=team)
    ProjectComponent.objects.create(project=project2, component=component2)

    # Create an SBOM for one of the components in project1
    SBOM.objects.create(
        name="Test SBOM",
        version="1.0",
        component=component1a,
        format="cyclonedx",
        sbom_filename="test.json",
        source="test",
    )

    url = reverse("api-1:get_dashboard_summary")
    response = client.get(
        f"{url}?project_id={project1.id}",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 200
    data = response.json()

    # Should show components within project1 only
    assert data["total_products"] == 0  # Products not filtered when viewing project
    assert data["total_projects"] == 1  # Just the queried project
    assert data["total_components"] == 2  # component1a, component1b
    assert len(data["latest_uploads"]) == 1  # Only SBOM from project1


@pytest.mark.django_db
def test_patch_public_status_billing_plan_restrictions(
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test that billing plan restrictions are enforced for public status toggling."""
    client = Client()

    # Create billing plans
    community_plan = BillingPlan.objects.create(
        key="community",
        name="Community",
        description="Free plan",
        max_products=1,
        max_projects=1,
        max_components=5,
    )

    business_plan = BillingPlan.objects.create(
        key="business",
        name="Business",
        description="Pro plan",
        max_products=5,
        max_projects=10,
        max_components=200,
    )

    # Set up session with team access
    team = sample_product.team
    setup_test_session(client, team, team.members.first())

    # Test URLs for all item types
    component_uri = reverse(
        "api-1:patch_item_public_status",
        kwargs={"item_type": "component", "item_id": sample_component.id},
    )

    project_uri = reverse(
        "api-1:patch_item_public_status",
        kwargs={"item_type": "project", "item_id": sample_project.id},
    )

    product_uri = reverse(
        "api-1:patch_item_public_status",
        kwargs={"item_type": "product", "item_id": sample_product.id},
    )

    # Test 1: Community plan users cannot make items private
    team.billing_plan = community_plan.key
    team.save()

    # Try to make component private - should fail
    response = client.patch(component_uri, json.dumps({"is_public": False}), content_type="application/json")
    assert response.status_code == 403
    assert "Community plan users cannot make items private" in response.json()["detail"]

    # Try to make project private - should fail
    response = client.patch(project_uri, json.dumps({"is_public": False}), content_type="application/json")
    assert response.status_code == 403
    assert "Community plan users cannot make items private" in response.json()["detail"]

    # Try to make product private - should fail
    response = client.patch(product_uri, json.dumps({"is_public": False}), content_type="application/json")
    assert response.status_code == 403
    assert "Community plan users cannot make items private" in response.json()["detail"]

    # Test 2: Community plan users can make items public (should succeed)
    response = client.patch(component_uri, json.dumps({"is_public": True}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Test 3: Business plan users can make items private
    team.billing_plan = business_plan.key
    team.save()

    # Should succeed for all item types
    for uri, item_name in [(component_uri, "component"), (project_uri, "project"), (product_uri, "product")]:
        response = client.patch(uri, json.dumps({"is_public": False}), content_type="application/json")
        assert response.status_code == 200, f"Failed for {item_name}: {response.content}"
        assert response.json()["is_public"] is False

        # And back to public
        response = client.patch(uri, json.dumps({"is_public": True}), content_type="application/json")
        assert response.status_code == 200
        assert response.json()["is_public"] is True

    # Test 4: Teams without billing plan can make items private (fallback behavior)
    team.billing_plan = None
    team.save()

    response = client.patch(component_uri, json.dumps({"is_public": False}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is False


@pytest.mark.django_db
def test_patch_public_status_enterprise_plan_unrestricted(
    sample_component: Component,  # noqa: F811
):
    """Test that enterprise plan users have no restrictions on public status."""
    client = Client()

    # Create enterprise plan
    enterprise_plan = BillingPlan.objects.create(
        key="enterprise",
        name="Enterprise",
        description="Enterprise plan",
        max_products=None,
        max_projects=None,
        max_components=None,
    )

    # Set up session
    team = sample_component.team
    team.billing_plan = enterprise_plan.key
    team.save()

    setup_test_session(client, team, team.members.first())

    component_uri = reverse(
        "api-1:patch_item_public_status",
        kwargs={"item_type": "component", "item_id": sample_component.id},
    )

    # Enterprise users should be able to make items private
    response = client.patch(component_uri, json.dumps({"is_public": False}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is False

    # And back to public
    response = client.patch(component_uri, json.dumps({"is_public": True}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True


@pytest.mark.django_db
@override_settings(BILLING=False)
def test_community_plan_restriction_bypassed_when_billing_disabled(sample_component, sample_access_token):
    """Test that community plan restrictions are bypassed when billing is disabled."""
    client = Client()
    url = reverse("api-1:patch_item_public_status", kwargs={"item_type": "component", "item_id": sample_component.id})

    # Set team to community plan
    sample_component.team.billing_plan = "community"
    sample_component.team.save()

    # Set up authentication and session
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    from .test_views import setup_test_session

    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    # Should be able to make item private even on community plan when billing is disabled
    response = client.patch(
        url,
        json.dumps({"is_public": False}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )

    assert response.status_code == 200
    assert response.json()["is_public"] is False

    # Verify in database
    sample_component.refresh_from_db()
    assert sample_component.is_public is False
