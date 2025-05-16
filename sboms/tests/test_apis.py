from __future__ import annotations

import json
import os
import pathlib

import pytest
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from access_tokens.models import AccessToken
from core.tests.fixtures import sample_user  # noqa: F401
from teams.fixtures import sample_team_with_owner_member  # noqa: F401
from teams.models import Member

from ..models import SBOM, Component, Product, Project
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

    test_file_path = pathlib.Path(__file__).parent.resolve() / "test_data/sbomify_spdx.json"
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
    assert sbom.sbom_filename == "a6325d19b1c584cd02b5e6002d381e8ffe2dcbadce06a3a9700c79df6716f8ed.json"
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

    test_file_path = pathlib.Path(__file__).parent.resolve() / "test_data/sbomify_cyclonedx.json"
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
    assert sbom.sbom_filename == "be643628f555d0d3c06de9502f08779e07baf61c7b02dda40b6c58a3bcee7d07.json"
    assert sbom.format == "cyclonedx"
    assert sbom.format_version == "1.6"
    assert sbom.version == ""
    # assert isinstance(sbom.licenses, list)
    # assert sbom.licenses.count() == 1
    assert sbom.licenses == [
        {"id": "BSD-3-Clause"},
        {"name": "custom test", "url": "https://custom.license/"},
    ]

    assert len(sbom.packages_licenses.keys()) == 92
    assert len([v[0] for v in sbom.packages_licenses.values() if v]) == 91

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

    assert response_json["supplier"] == {"contacts": []}
    assert response_json["authors"] == []
    assert response_json["licenses"] == []
    assert len(response_json.keys()) == 3

    # Set component metadata
    component_metadata = {
        "supplier": {
            "name": "Test supplier",
            "url": "http://supply.org",
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

    response = client.put(
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
                "url": "http://another-supply.org",
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
    assert sample_component.metadata["supplier"]["url"] == "http://another-supply.org"
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
            "url": "http://supply.org",
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
    assert response_json["supplier"]["url"][0] == component_metadata["supplier"]["url"]
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
    assert response_json["licenses"][0]["license"]["id"] == component_metadata["licenses"][0]

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
            "url": "http://supply.org",
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
def test_get_stats(
    sample_user: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_product: Product,  # noqa: F811
    sample_project: Project,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_team_with_owner_member,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    client = Client()

    # upload sbom using the test_sbom_upload_api_cyclonedx test case function
    test_sbom_upload_api_cyclonedx(sample_access_token, sample_component, mocker)

    # Test invalid team key
    url = reverse("api-1:get_stats") + "?team_key=invalid-team"
    response = client.get(
        url,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Team not found"

    # Test valid team key without item type
    url = reverse("api-1:get_stats") + f"?team_key={sample_team_with_owner_member.team.key}"
    response = client.get(
        url,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 200
    stats = response.json()

    assert "total_products" in stats
    assert "total_projects" in stats
    assert "total_components" in stats
    assert "license_count" in stats
    assert "component_uploads" in stats

    assert stats["total_products"] == 1
    assert stats["total_projects"] == 1
    assert stats["total_components"] == 1
    assert stats["license_count"]["BSD-3-Clause"] == 20
    assert stats["license_count"]["MIT"] == 47
    assert stats["license_count"]["BSD-2-Clause"] == 2
    assert stats["license_count"]["Apache-2.0"] == 9
    assert stats["license_count"]["MPL-2.0"] == 1
    assert stats["license_count"]["PSFL"] == 1
    assert stats["license_count"]["PSF-2.0"] == 1
    assert stats["license_count"]["Apachev2 or later or GPLv2"] == 1
    assert stats["license_count"]["Unlicense"] == 1
    assert stats["license_count"]["UNKNOWN"] == 4
    assert stats["license_count"]["ISC"] == 3
    assert stats["license_count"]["LGPL with exceptions"] == 1

    assert len(stats["component_uploads"]) == 1
    assert stats["component_uploads"][0]["component_name"] == "test component"
    assert stats["component_uploads"][0]["sbom_name"] == "sbomify-backend"
    assert stats["component_uploads"][0]["sbom_version"] == ""

    # Test with specific item type
    url = reverse("api-1:get_stats")
    response = client.get(
        url + "?item_type=component",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "item_id is required when item_type is provided"

    # Test with specific item type and ID
    url = reverse("api-1:get_stats")
    response = client.get(
        url + f"?item_type=component&item_id={sample_component.id}",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 200
    stats = response.json()
    assert "total_products" in stats
    assert "total_projects" in stats
    assert "total_components" in stats
    assert "license_count" in stats
    assert "component_uploads" in stats

    # Test with neither team nor item_id
    url = reverse("api-1:get_stats")
    response = client.get(
        url,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {sample_access_token.encoded_token}",
    )
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_products"] is None
    assert stats["total_projects"] is None
    assert stats["total_components"] is None
    assert stats["license_count"] == {}
    assert stats["component_uploads"] == []


@pytest.mark.django_db
def test_get_stats_public(
    sample_user: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_product: Product,  # noqa: F811
):
    client = Client()

    # Test product stats public access when product is private
    url = reverse("api-1:get_stats") + f"?item_type=product&item_id={sample_product.id}"

    response = client.get(url)
    assert response.status_code == 403
    assert response.json()["detail"] == "Authentication required"

    # Make the product public and test again
    sample_product.is_public = True
    sample_product.save()

    response = client.get(url)
    assert response.status_code == 200
