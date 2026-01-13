from __future__ import annotations

import json
import os
import pathlib

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from pytest_mock.plugin import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import ContactProfile, Member

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

    # Use core API endpoints instead of removed public_status endpoints
    component_uri = reverse("api-1:patch_component", kwargs={"component_id": sample_sbom.component.id})
    project_uri = reverse("api-1:patch_project", kwargs={"project_id": sample_project.id})
    product_uri = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})

    component_get_uri = reverse("api-1:get_component", kwargs={"component_id": sample_sbom.component.id})
    project_get_uri = reverse("api-1:get_project", kwargs={"project_id": sample_project.id})
    product_get_uri = reverse("api-1:get_product", kwargs={"product_id": sample_product.id})

    # Set up session with team access
    setup_test_session(client, sample_product.team, sample_product.team.members.first())

    # Make the component public
    response = client.patch(component_uri, json.dumps({"is_public": True}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Verify component is public
    response = client.get(component_get_uri, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Make the project public
    response = client.patch(project_uri, json.dumps({"is_public": True}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Verify project is public
    response = client.get(project_get_uri, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Make the product public
    response = client.patch(product_uri, json.dumps({"is_public": True}), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Verify product is public
    response = client.get(product_get_uri, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["is_public"] is True


@pytest.mark.django_db
def test_sbom_upload_api_spdx(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    mocker.patch("boto3.resource")
    patched_upload_data_as_file = mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")
    SBOM.objects.all().delete()

    test_file_path = pathlib.Path(__file__).parent.resolve() / "test_data/sbomify_trivy.spdx.json"
    sbom_data = open(test_file_path, "r").read()

    client = Client()

    url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=sbom_data,
        content_type="application/json",
        **get_api_headers(sample_access_token),
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
    patched_upload_data_as_file = mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    test_file_path = pathlib.Path(__file__).parent.resolve() / "test_data/sbomify_trivy.cdx.json"
    sbom_data = open(test_file_path, "r").read()

    client = Client()

    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=sbom_data,
        content_type="application/json",
        **get_api_headers(sample_access_token),
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
def test_sbom_upload_api_cyclonedx_1_6_with_manufacturer(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that CycloneDX 1.6 SBOMs with manufacturer field are accepted."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "manufacturer": {"name": "Test Manufacturer"},
                        "name": "test-tool",
                        "version": "1.0.0",
                    }
                ]
            },
            "component": {"type": "application", "name": "test-component", "version": "1.0.0"},
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    assert "id" in response.json()

    # Verify the SBOM was created correctly
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.component.id == sample_component.id
    assert sbom.format == "cyclonedx"
    assert sbom.format_version == "1.6"
    assert sbom.name == "test-component"


@pytest.mark.django_db
def test_sbom_upload_api_cyclonedx_1_5(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that CycloneDX 1.5 SBOMs are still accepted."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "test-component-1.5", "version": "2.0.0"}},
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    assert "id" in response.json()

    # Verify the SBOM was created correctly
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.component.id == sample_component.id
    assert sbom.format == "cyclonedx"
    assert sbom.format_version == "1.5"
    assert sbom.name == "test-component-1.5"


@pytest.mark.django_db
def test_sbom_upload_api_cyclonedx_unsupported_version(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that unsupported CycloneDX versions are rejected."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "2.0",
        "metadata": {},
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "Unsupported CycloneDX specVersion" in response.json()["detail"]


@pytest.mark.django_db
def test_sbom_upload_api_cyclonedx_invalid_json(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that invalid JSON is rejected."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data="not valid json{",
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    # Django Ninja returns "Cannot parse request body" for invalid JSON before our function runs
    assert "Invalid JSON" in response.json()["detail"] or "Cannot parse request body" in response.json()["detail"]


@pytest.mark.django_db
def test_cyclonedx_1_6_manufacturer_field(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test CycloneDX 1.6 specific feature: 'manufacturer' field (vs 1.5's 'manufacture')."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # CycloneDX 1.6 uses 'manufacturer' (correct spelling)
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "manufacturer": {"name": "Acme Corp", "url": ["https://acme.com"]},  # 1.6: manufacturer
            "component": {"type": "application", "name": "test-app", "version": "1.0.0"},
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.format_version == "1.6"


@pytest.mark.django_db
def test_cyclonedx_1_5_manufacture_field(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test CycloneDX 1.5 specific feature: 'manufacture' field (typo, fixed in 1.6)."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # CycloneDX 1.5 uses 'manufacture' (missing 'r'), this was a typo fixed in 1.6
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "manufacture": {"name": "Old Corp"},  # 1.5: manufacture (typo)
            "component": {"type": "application", "name": "legacy-app", "version": "1.0.0"},
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.format_version == "1.5"


@pytest.mark.django_db
def test_cyclonedx_1_6_declarations_field(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test CycloneDX 1.6 new feature: declarations field for conformance/attestations."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # CycloneDX 1.6 introduced 'declarations' for conformance tracking
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "compliant-app", "version": "1.0.0"},
        },
        "declarations": {  # New in 1.6
            "assessors": [
                {
                    "bom-ref": "assessor-1",
                    "thirdParty": False,
                    "organization": {"name": "Internal Security Team"},
                }
            ]
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.format_version == "1.6"


@pytest.mark.django_db
def test_cyclonedx_1_7_citations_field(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test CycloneDX 1.7 new feature: citations for data attribution tracking."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # CycloneDX 1.7 adds 'citations' for tracking who supplied what data
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "modern-app", "version": "2.0.0"},
        },
        "citations": [  # New in 1.7
            {
                "timestamp": "2025-11-27T00:00:00Z",
                "pointers": ["/metadata/component/name"],
                "attributedTo": "org-123",
            }
        ],
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.format == "cyclonedx"
    assert sbom.format_version == "1.7"
    assert sbom.name == "modern-app"


@pytest.mark.django_db
def test_cyclonedx_1_7_distribution_constraints(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test CycloneDX 1.7 new feature: distributionConstraints with TLP classification."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # CycloneDX 1.7 adds distributionConstraints with Traffic Light Protocol (TLP)
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "sensitive-app", "version": "1.0.0"},
            "distributionConstraints": {  # New in 1.7
                "tlp": "AMBER"  # Traffic Light Protocol classification
            },
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.format_version == "1.7"


@pytest.mark.django_db
def test_cyclonedx_1_7_patents_in_definitions(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test CycloneDX 1.7 enhancement: patents field added to definitions (not in 1.6)."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # CycloneDX 1.7 adds 'patents' to definitions (1.6 definitions only had standards)
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "app-with-patents", "version": "1.0.0"},
        },
        "definitions": {
            "patents": []  # New in 1.7 - empty list is valid
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.format_version == "1.7"


@pytest.mark.django_db
def test_cyclonedx_1_6_rejects_citations_field(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that CycloneDX 1.6 rejects 'citations' field (only in 1.7+)."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # Try to use 1.7 'citations' field with 1.6 spec
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "test-app", "version": "1.0.0"},
        },
        "citations": [  # Not valid in 1.6, only in 1.7+
            {
                "timestamp": "2025-11-27T00:00:00Z",
                "pointers": ["/metadata/component/name"],
                "attributedTo": "org-123",
            }
        ],
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    # Should fail validation because 1.6 doesn't allow 'citations'
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Invalid CycloneDX 1.6 format" in detail or "Extra inputs are not permitted" in detail


@pytest.mark.django_db
def test_cyclonedx_1_6_definitions_rejects_patents(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that CycloneDX 1.6 definitions field rejects 'patents' (added in 1.7)."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # Try to use 1.7 'patents' inside definitions with 1.6 spec
    # Note: 1.6 HAS definitions, but only with 'standards', not 'patents'
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "test-app", "version": "1.0.0"},
        },
        "definitions": {
            "patents": []  # Not valid in 1.6 definitions, only in 1.7+
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    # Should fail validation because 1.6 definitions don't support 'patents'
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Invalid CycloneDX 1.6 format" in detail or "Extra inputs are not permitted" in detail


@pytest.mark.django_db
def test_cyclonedx_1_6_rejects_distribution_constraints(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that CycloneDX 1.6 rejects 'distributionConstraints' field (only in 1.7+)."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # Try to use 1.7 'distributionConstraints' with 1.6 spec
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "test-app", "version": "1.0.0"},
            "distributionConstraints": {"tlp": "AMBER"},  # Not valid in 1.6
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    # Should fail validation because 1.6 doesn't allow 'distributionConstraints'
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Invalid CycloneDX 1.6 format" in detail or "Extra inputs are not permitted" in detail


@pytest.mark.django_db
def test_cyclonedx_1_5_rejects_declarations_field(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that CycloneDX 1.5 rejects 'declarations' field (only in 1.6+)."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    # Try to use 1.6 'declarations' field with 1.5 spec
    sbom_data = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "test-app", "version": "1.0.0"},
        },
        "declarations": {  # Not valid in 1.5
            "assessors": [{"bom-ref": "assessor-1", "thirdParty": False}]
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    # Should fail validation because 1.5 doesn't allow 'declarations'
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Invalid CycloneDX 1.5 format" in detail or "Extra inputs are not permitted" in detail


@pytest.mark.django_db
def test_spdx_2_2_with_document_describes(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test SPDX 2.2 with documentDescribes field (deprecated in 2.3, use relationships instead)."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    sbom_data = {
        "spdxVersion": "SPDX-2.2",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "test-package-2.2",
        "documentNamespace": "https://example.com/test-2.2",
        "creationInfo": {
            "created": "2023-01-01T00:00:00Z",
            "creators": ["Tool: test-tool"],
        },
        "documentDescribes": ["SPDXRef-Package"],  # Valid in 2.2, deprecated in 2.3
        "packages": [
            {
                "SPDXID": "SPDXRef-Package",
                "name": "test-package-2.2",
                "versionInfo": "1.0.0",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
            }
        ],
    }

    client = Client()
    url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.format == "spdx"
    assert sbom.format_version == "2.2"
    assert sbom.name == "test-package-2.2"


@pytest.mark.django_db
def test_spdx_2_3_with_relationships(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test SPDX 2.3 using relationships (preferred over deprecated documentDescribes)."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    sbom_data = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "test-package-2.3",
        "documentNamespace": "https://example.com/test-2.3",
        "creationInfo": {
            "created": "2023-01-01T00:00:00Z",
            "creators": ["Tool: test-tool"],
        },
        "packages": [
            {
                "SPDXID": "SPDXRef-Package",
                "name": "test-package-2.3",
                "versionInfo": "1.0.0",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
            }
        ],
        "relationships": [  # Preferred in 2.3 over documentDescribes
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Package",
            }
        ],
    }

    client = Client()
    url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.format == "spdx"
    assert sbom.format_version == "2.3"
    assert sbom.name == "test-package-2.3"


@pytest.mark.django_db
def test_spdx_2_3_enhanced_external_ref_types(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test SPDX 2.3 enhanced external reference types (PERSISTENT_ID, PACKAGE_MANAGER)."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    sbom_data = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "test-package-2.3",
        "documentNamespace": "https://example.com/test-2.3",
        "creationInfo": {
            "created": "2023-01-01T00:00:00Z",
            "creators": ["Tool: test-tool"],
        },
        "packages": [
            {
                "SPDXID": "SPDXRef-Package",
                "name": "test-package-2.3",
                "versionInfo": "1.0.0",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE_MANAGER",  # 2.3 allows underscore variant
                        "referenceType": "purl",
                        "referenceLocator": "pkg:npm/test@1.0.0",
                    }
                ],
            }
        ],
    }

    client = Client()
    url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 201
    sbom = SBOM.objects.get(id=response.json()["id"])
    assert sbom.format == "spdx"
    assert sbom.format_version == "2.3"


@pytest.mark.django_db
def test_spdx_unsupported_version(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that unsupported SPDX versions are rejected."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    sbom_data = {
        "spdxVersion": "SPDX-3.0",  # Not yet supported
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "test-package-3.0",
        "documentNamespace": "https://example.com/test-3.0",
        "creationInfo": {
            "created": "2023-01-01T00:00:00Z",
            "creators": ["Tool: test-tool"],
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "Unsupported SPDX version: 3.0" in response.json()["detail"]
    assert "2.2, 2.3" in response.json()["detail"]  # Lists supported versions


@pytest.mark.django_db
def test_spdx_invalid_version_format(
    sample_access_token: AccessToken,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test that invalid SPDX version format is rejected."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

    SBOM.objects.all().delete()

    sbom_data = {
        "spdxVersion": "2.3",  # Missing "SPDX-" prefix
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "test-package",
        "creationInfo": {
            "created": "2023-01-01T00:00:00Z",
            "creators": ["Tool: test-tool"],
        },
    }

    client = Client()
    url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})
    response = client.post(
        url,
        data=json.dumps(sbom_data),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 400
    assert "Invalid spdxVersion format" in response.json()["detail"]
    assert "Expected format: SPDX-X.X" in response.json()["detail"]


@pytest.mark.django_db
def test_get_and_set_component_metadata(sample_component: Component, sample_access_token: AccessToken):  # noqa: F811
    client = Client()

    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})

    # Get unset metadata
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    response_json = response.json()

    assert response_json["id"] == sample_component.id
    assert response_json["name"] == sample_component.name
    assert response_json["supplier"] == {"contacts": []}
    assert response_json["manufacturer"] == {"contacts": []}
    assert response_json["authors"] == []
    assert response_json["licenses"] == []
    assert response_json["lifecycle_phase"] is None
    assert response_json["contact_profile_id"] is None
    assert response_json["contact_profile"] is None
    assert response_json["uses_custom_contact"] is True
    assert len(response_json.keys()) == 10

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
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Get metadata again and verify it was set
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
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
    assert response_data["contact_profile_id"] is None
    assert response_data["contact_profile"] is None
    assert response_data["uses_custom_contact"] is True


@pytest.mark.django_db
def test_component_metadata_with_contact_profile(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    client = Client()

    from sbomify.apps.teams.models import ContactEntity, ContactProfileContact

    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Shared Profile",
        is_default=True,
    )
    # Create entity with all roles for backward compatibility
    entity = ContactEntity.objects.create(
        profile=profile,
        name="Example Supplier",
        email="profile@example.com",
        phone="+1 555 0100",
        address="123 Example Street",
        website_urls=["https://supplier.example.com"],
        is_manufacturer=True,
        is_supplier=True,
    )
    ContactProfileContact.objects.create(
        entity=entity,
        name="Profile Owner",
        email="owner@example.com",
        phone="555-1000",
    )

    patch_url = reverse("api-1:patch_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.patch(
        patch_url,
        json.dumps({"contact_profile_id": profile.id}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    get_url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.get(
        get_url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    response_data = response.json()

    assert response_data["contact_profile_id"] == profile.id
    assert response_data["contact_profile"]["name"] == "Shared Profile"
    assert response_data["uses_custom_contact"] is False
    # Entity is both supplier and manufacturer
    assert response_data["supplier"]["name"] == "Example Supplier"
    assert response_data["supplier"]["address"] == "123 Example Street"
    assert response_data["supplier"]["url"] == ["https://supplier.example.com"]
    assert response_data["supplier"]["contacts"][0]["name"] == "Profile Owner"
    # Manufacturer should also be populated from the same entity
    assert response_data["manufacturer"]["name"] == "Example Supplier"
    assert response_data["manufacturer"]["address"] == "123 Example Street"
    assert response_data["manufacturer"]["url"] == ["https://supplier.example.com"]
    assert response_data["manufacturer"]["contacts"][0]["name"] == "Profile Owner"


@pytest.mark.django_db
def test_component_metadata_separate_manufacturer_supplier(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test component metadata with separate manufacturer and supplier entities."""
    client = Client()

    from sbomify.apps.teams.models import ContactEntity, ContactProfileContact

    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Separate Entities Profile",
        is_default=False,
    )
    # Create manufacturer entity
    manufacturer_entity = ContactEntity.objects.create(
        profile=profile,
        name="Acme Manufacturing Corp",
        email="info@acme-mfg.com",
        phone="+1 555 1000",
        address="100 Factory Lane",
        website_urls=["https://acme-mfg.com"],
        is_manufacturer=True,
        is_supplier=False,
    )
    ContactProfileContact.objects.create(
        entity=manufacturer_entity,
        name="John Manufacturer",
        email="john@acme-mfg.com",
        phone="555-1001",
    )
    # Create supplier entity
    supplier_entity = ContactEntity.objects.create(
        profile=profile,
        name="Global Supply Inc",
        email="info@global-supply.com",
        phone="+1 555 2000",
        address="200 Distribution Road",
        website_urls=["https://global-supply.com"],
        is_manufacturer=False,
        is_supplier=True,
    )
    ContactProfileContact.objects.create(
        entity=supplier_entity,
        name="Jane Supplier",
        email="jane@global-supply.com",
        phone="555-2001",
    )

    patch_url = reverse("api-1:patch_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.patch(
        patch_url,
        json.dumps({"contact_profile_id": profile.id}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 204

    get_url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.get(
        get_url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    response_data = response.json()

    assert response_data["contact_profile_id"] == profile.id
    assert response_data["uses_custom_contact"] is False

    # Manufacturer should come from manufacturer entity
    assert response_data["manufacturer"]["name"] == "Acme Manufacturing Corp"
    assert response_data["manufacturer"]["address"] == "100 Factory Lane"
    assert response_data["manufacturer"]["url"] == ["https://acme-mfg.com"]
    assert response_data["manufacturer"]["contacts"][0]["name"] == "John Manufacturer"

    # Supplier should come from supplier entity (different from manufacturer)
    assert response_data["supplier"]["name"] == "Global Supply Inc"
    assert response_data["supplier"]["address"] == "200 Distribution Road"
    assert response_data["supplier"]["url"] == ["https://global-supply.com"]
    assert response_data["supplier"]["contacts"][0]["name"] == "Jane Supplier"


@pytest.mark.django_db
def test_component_copy_metadata_api(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    client = Client()

    # Create another component and set its metadata using the API
    another_component = Component.objects.create(
        name="Another Component",
        team_id=sample_component.team_id,
    )

    # Set metadata via API to ensure it gets stored in native fields
    metadata_url = reverse("api-1:patch_component_metadata", kwargs={"component_id": another_component.id})
    metadata_to_set = {
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
        "lifecycle_phase": "design",
    }

    response = client.patch(
        metadata_url,
        json.dumps(metadata_to_set),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 204

    # Use the new approach: GET source metadata + PATCH target
    # First, get metadata from source component
    source_url = reverse("api-1:get_component_metadata", kwargs={"component_id": another_component.id})
    response = client.get(
        source_url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200
    source_metadata = response.json()

    # Remove component-specific fields (id, name) that shouldn't be copied
    metadata_to_copy = {k: v for k, v in source_metadata.items() if k not in ("id", "name")}

    # Then, patch the target component with the copied metadata
    target_url = reverse("api-1:patch_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.patch(
        target_url,
        json.dumps(metadata_to_copy),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Verify that sample_component's metadata has been set by checking the API response
    verify_url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.get(
        verify_url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200
    result_metadata = response.json()

    assert result_metadata["supplier"]["name"] == "Another supplier"
    assert result_metadata["supplier"]["url"] == ["http://another-supply.org"]
    assert result_metadata["supplier"]["contacts"][0]["name"] == "C2"
    assert result_metadata["authors"][0]["name"] == "B1"
    assert result_metadata["licenses"][0] == "MIT"
    assert result_metadata["lifecycle_phase"] == "design"


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

    # Use PATCH endpoint to set metadata through native fields
    metadata_url = reverse("api-1:patch_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.patch(
        metadata_url,
        json.dumps(component_metadata),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 204

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
        **get_api_headers(sample_access_token),
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
        **get_api_headers(sample_access_token),
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
        **get_api_headers(sample_access_token),
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
        **get_api_headers(sample_access_token),
        data=json.dumps(sbom_metadata),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing required 'component' field in SBOM metadata"


@pytest.mark.django_db
def test_cyclonedx_1_7_metadata_endpoint(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test CycloneDX 1.7 metadata endpoint with version-specific handling."""
    client = Client()

    # Set component metadata first
    component_metadata = {
        "supplier": {
            "name": "Test Supplier 1.7",
            "url": ["https://supplier17.com"],
            "address": "123 Future Street",
            "contacts": [{"name": "Contact 1.7", "email": "contact@supplier17.com"}],
        },
        "authors": [{"name": "Author 1.7", "email": "author@example.com"}],
        "licenses": ["MIT"],
    }

    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.patch(
        url,
        json.dumps(component_metadata),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 204

    # Now test the CycloneDX 1.7 metadata endpoint
    sbom_metadata = {
        "timestamp": "2025-11-27T00:00:00+00:00",
        "component": {
            "bom-ref": "component-1.7",
            "type": "application",
            "name": "test-app-1.7",
            "version": "2.0.0",
        },
    }

    url = reverse(
        "api-1:get_cyclonedx_component_metadata",
        kwargs={"spec_version": "1.7", "component_id": sample_component.id},
    )

    response = client.post(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
        data=json.dumps(sbom_metadata),
    )

    assert response.status_code == 200
    response_json = response.json()

    # Verify 1.7 metadata structure includes component metadata
    # The endpoint merges component metadata with SBOM metadata
    assert response_json["component"]["name"] == "test-app-1.7"
    assert response_json["component"]["version"] == "2.0.0"

    # Component metadata should be included
    if "supplier" in response_json:
        assert response_json["supplier"]["name"] == "Test Supplier 1.7"
        # 1.7 supports PostalAddress (like 1.6)
        if "address" in response_json["supplier"]:
            assert response_json["supplier"]["address"]["streetAddress"] == "123 Future Street"

    # Test version override for 1.7 (should use Version object like 1.6)
    response = client.post(
        url + "?sbom_version=3.0.0",
        content_type="application/json",
        **get_api_headers(sample_access_token),
        data=json.dumps(sbom_metadata),
    )

    assert response.status_code == 200
    response_json = response.json()
    # In 1.7, version should be a Version object (like 1.6)
    assert response_json["component"]["version"] == "3.0.0"


@pytest.mark.django_db
def test_cyclonedx_metadata_with_manufacturer(
    sample_component: Component,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
):
    """Test that manufacturer is included in CycloneDX 1.6+ metadata generation."""
    client = Client()

    from sbomify.apps.teams.models import ContactEntity, ContactProfileContact

    # Create profile with separate manufacturer and supplier entities
    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Manufacturer Test Profile",
    )
    manufacturer_entity = ContactEntity.objects.create(
        profile=profile,
        name="Test Manufacturer Inc",
        email="info@test-mfg.com",
        phone="+1 555 3000",
        address="300 Manufacturing Blvd",
        website_urls=["https://test-mfg.com"],
        is_manufacturer=True,
        is_supplier=False,
    )
    ContactProfileContact.objects.create(
        entity=manufacturer_entity,
        name="Mfg Contact",
        email="mfg@test-mfg.com",
        phone="555-3001",
    )
    supplier_entity = ContactEntity.objects.create(
        profile=profile,
        name="Test Supplier LLC",
        email="info@test-supplier.com",
        phone="+1 555 4000",
        address="400 Supply Ave",
        website_urls=["https://test-supplier.com"],
        is_manufacturer=False,
        is_supplier=True,
    )
    ContactProfileContact.objects.create(
        entity=supplier_entity,
        name="Supplier Contact",
        email="supplier@test-supplier.com",
        phone="555-4001",
    )

    # Link contact profile to component
    patch_url = reverse("api-1:patch_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.patch(
        patch_url,
        json.dumps({"contact_profile_id": profile.id}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 204

    # Test CycloneDX 1.6 metadata generation (manufacturer supported)
    sbom_metadata = {
        "timestamp": "2025-12-01T00:00:00+00:00",
        "component": {
            "bom-ref": "test-component",
            "type": "application",
            "name": "test-app",
            "version": "1.0.0",
        },
    }

    url = reverse(
        "api-1:get_cyclonedx_component_metadata",
        kwargs={"spec_version": "1.6", "component_id": sample_component.id},
    )
    response = client.post(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
        data=json.dumps(sbom_metadata),
    )

    assert response.status_code == 200
    response_json = response.json()

    # Verify manufacturer is in the response (CycloneDX 1.6+)
    assert "manufacturer" in response_json
    assert response_json["manufacturer"]["name"] == "Test Manufacturer Inc"
    assert response_json["manufacturer"]["url"] == ["https://test-mfg.com"]
    assert response_json["manufacturer"]["address"]["streetAddress"] == "300 Manufacturing Blvd"
    assert response_json["manufacturer"]["contact"][0]["name"] == "Mfg Contact"
    assert response_json["manufacturer"]["contact"][0]["email"] == "mfg@test-mfg.com"

    # Verify supplier is also present and different
    assert "supplier" in response_json
    assert response_json["supplier"]["name"] == "Test Supplier LLC"
    assert response_json["supplier"]["url"] == ["https://test-supplier.com"]

    # Test CycloneDX 1.5 (manufacturer NOT supported in metadata)
    url_1_5 = reverse(
        "api-1:get_cyclonedx_component_metadata",
        kwargs={"spec_version": "1.5", "component_id": sample_component.id},
    )
    response = client.post(
        url_1_5,
        content_type="application/json",
        **get_api_headers(sample_access_token),
        data=json.dumps(sbom_metadata),
    )

    assert response.status_code == 200
    response_json = response.json()

    # manufacturer should NOT be in 1.5 response
    assert "manufacturer" not in response_json
    # supplier should still be present
    assert "supplier" in response_json
    assert response_json["supplier"]["name"] == "Test Supplier LLC"


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
        **get_api_headers(sample_access_token),
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
        **get_api_headers(sample_access_token),
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
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Get metadata and verify license expressions are preserved
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
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
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Get metadata and verify URL was handled correctly
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
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
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 204

    # Now, only update the lifecycle_phase using PATCH
    partial_update = {"lifecycle_phase": "build"}

    response = client.patch(
        url,
        json.dumps(partial_update),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 204

    # Verify that only lifecycle_phase was updated and other fields remain unchanged
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
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
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204

    # Get metadata and verify authors were saved correctly
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
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
def test_component_metadata_includes_profile_authors_in_response(
    sample_component: Component, sample_access_token: AccessToken  # noqa: F811
):
    """Test that the API response includes profile authors in contact_profile.authors for frontend syncing.
    
    This test verifies the API response structure, not database-level syncing.
    The frontend is responsible for syncing authors from profile to component display.
    """
    from sbomify.apps.teams.models import AuthorContact, ContactProfile

    client = Client()

    # Create a profile with authors
    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Test Profile",
        is_default=False,
    )
    AuthorContact.objects.create(
        profile=profile,
        name="Profile Author One",
        email="profile1@example.com",
        phone="111-111-1111",
        order=0,
    )
    AuthorContact.objects.create(
        profile=profile,
        name="Profile Author Two",
        email="profile2@example.com",
        phone="222-222-2222",
        order=1,
    )

    # Assign profile to component
    sample_component.contact_profile = profile
    sample_component.save()

    # Get metadata - should return authors from profile
    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["contact_profile_id"] == profile.id
    # Verify profile authors are available in contact_profile field for frontend syncing
    assert "contact_profile" in response_data
    assert "authors" in response_data["contact_profile"]
    assert len(response_data["contact_profile"]["authors"]) == 2
    assert response_data["contact_profile"]["authors"][0]["name"] == "Profile Author One"
    assert response_data["contact_profile"]["authors"][0]["email"] == "profile1@example.com"
    assert response_data["contact_profile"]["authors"][1]["name"] == "Profile Author Two"
    assert response_data["contact_profile"]["authors"][1]["email"] == "profile2@example.com"


@pytest.mark.django_db
def test_component_metadata_api_includes_updated_profile_authors(
    sample_component: Component, sample_access_token: AccessToken  # noqa: F811
):
    """Test that when profile authors change, the API response includes updated profile authors.
    
    This test verifies the API response structure includes updated profile authors
    in contact_profile.authors for frontend consumption. The frontend handles
    syncing these to the component display.
    """
    from sbomify.apps.teams.models import AuthorContact, ContactProfile

    client = Client()

    # Create a profile with initial authors
    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Test Profile",
        is_default=False,
    )
    AuthorContact.objects.create(
        profile=profile,
        name="Original Author",
        email="original@example.com",
        order=0,
    )

    # Assign profile to component
    sample_component.contact_profile = profile
    sample_component.save()

    # Get metadata - should return initial author
    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200
    response_data = response.json()
    # Verify profile authors are available in contact_profile field
    assert "contact_profile" in response_data
    assert "authors" in response_data["contact_profile"]
    assert len(response_data["contact_profile"]["authors"]) == 1
    assert response_data["contact_profile"]["authors"][0]["name"] == "Original Author"

    # Add new author to profile
    AuthorContact.objects.create(
        profile=profile,
        name="New Author",
        email="new@example.com",
        order=1,
    )

    # Get metadata again - should reflect new author in contact_profile
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200
    response_data = response.json()
    # Verify updated profile authors are available for frontend syncing
    assert len(response_data["contact_profile"]["authors"]) == 2
    assert response_data["contact_profile"]["authors"][0]["name"] == "Original Author"
    assert response_data["contact_profile"]["authors"][1]["name"] == "New Author"


@pytest.mark.django_db
def test_component_metadata_api_returns_empty_authors_when_profile_has_none(
    sample_component: Component, sample_access_token: AccessToken  # noqa: F811
):
    """Test that when a profile has no authors, the API response includes empty authors list.
    
    This test verifies the API response structure shows empty authors in contact_profile.authors
    when the profile has no authors. The frontend handles syncing this to the component display.
    Note: This does not verify database-level clearing - the API only returns the response structure.
    """
    from sbomify.apps.sboms.models import ComponentAuthor
    from sbomify.apps.teams.models import ContactProfile

    client = Client()

    # Create component with existing authors
    ComponentAuthor.objects.create(
        component=sample_component,
        name="Component Author",
        email="component@example.com",
        order=0,
    )
    assert sample_component.authors.count() == 1

    # Create a profile without authors
    profile = ContactProfile.objects.create(
        team=sample_component.team,
        name="Empty Profile",
        is_default=False,
    )
    assert profile.authors.count() == 0

    # Assign profile to component
    sample_component.contact_profile = profile
    sample_component.save()

    # Get metadata - should return empty authors list
    url = reverse("api-1:get_component_metadata", kwargs={"component_id": sample_component.id})
    response = client.get(
        url,
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["contact_profile_id"] == profile.id
    # Verify profile has no authors (empty list in contact_profile.authors)
    assert "contact_profile" in response_data
    assert "authors" in response_data["contact_profile"]
    assert response_data["contact_profile"]["authors"] == []


@pytest.mark.django_db
def test_sbom_upload_file_cyclonedx(
    sample_user,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    mocker.patch("boto3.resource")
    patched_upload_data_as_file = mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")
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
    patched_upload_data_as_file = mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")
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
    mock_delete_object = mocker.patch("sbomify.apps.core.object_store.S3Client.delete_object")

    client = Client()

    # Test unauthorized access (no token)
    url = reverse("api-1:delete_sbom", kwargs={"sbom_id": sample_sbom.id})
    response = client.delete(url)
    assert response.status_code == 401

    # Test with valid token and permissions
    response = client.delete(
        url,
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 204
    assert SBOM.objects.filter(id=sample_sbom.id).count() == 0

    # Verify S3 file deletion was attempted
    mock_delete_object.assert_called_once()

    # Test deleting non-existent SBOM
    response = client.delete(
        url,
        **get_api_headers(sample_access_token),
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

    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.access_tokens.utils import create_personal_access_token
    from sbomify.apps.core.tests.shared_fixtures import get_api_headers

    User = get_user_model()
    other_user = User.objects.create_user(username="otheruser", password="password")
    token_str = create_personal_access_token(other_user)
    other_token = AccessToken.objects.create(user=other_user, encoded_token=token_str, description="Test Token")

    client = Client()
    url = reverse("api-1:delete_sbom", kwargs={"sbom_id": sample_sbom.id})

    response = client.delete(
        url,
        **get_api_headers(other_token),
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
    from sbomify.apps.sboms.models import SBOM, Component, Product, ProductProject, Project, ProjectComponent

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
        **get_api_headers(sample_access_token),
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
    from sbomify.apps.sboms.models import SBOM, Component, Project, ProjectComponent

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
        **get_api_headers(sample_access_token),
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
    sample_access_token: AccessToken,  # noqa: F811
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
        description="Business plan for medium teams",
        max_products=5,
        max_projects=10,
        max_components=200,
    )

    # Set up authentication and session
    team = sample_product.team
    assert client.login(username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"])
    setup_test_session(client, team, team.members.first())

    # Test URLs for all item types
    component_uri = reverse("api-1:patch_component", kwargs={"component_id": sample_component.id})
    project_uri = reverse("api-1:patch_project", kwargs={"project_id": sample_project.id})
    product_uri = reverse("api-1:patch_product", kwargs={"product_id": sample_product.id})

    # Test 1: Community plan users cannot make items private
    team.billing_plan = community_plan.key
    team.save()

    # First, make all items public so we can test making them private
    for uri in [component_uri, project_uri, product_uri]:
        client.patch(
            uri,
            json.dumps({"is_public": True}),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )

    # Try to make component private - should fail
    response = client.patch(
        component_uri,
        json.dumps({"is_public": False}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 403
    assert "Community plan users cannot make items private" in response.json()["detail"]

    # Try to make project private - should fail
    response = client.patch(
        project_uri,
        json.dumps({"is_public": False}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 403
    assert "Community plan users cannot make items private" in response.json()["detail"]

    # Try to make product private - should fail
    response = client.patch(
        product_uri,
        json.dumps({"is_public": False}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 403
    assert "Community plan users cannot make items private" in response.json()["detail"]

    # Test 2: Community plan users can make items public (should succeed)
    response = client.patch(
        component_uri,
        json.dumps({"is_public": True}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Test 3: Business plan users can make items private
    team.billing_plan = business_plan.key
    team.save()

    # Need to handle hierarchy constraints: make product private first, then project, then component
    # Product can be made private independently
    response = client.patch(
        product_uri,
        json.dumps({"is_public": False}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200, f"Failed for product: {response.content}"
    assert response.json()["is_public"] is False

    # Project can be made private independently
    response = client.patch(
        project_uri,
        json.dumps({"is_public": False}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200, f"Failed for project: {response.content}"
    assert response.json()["is_public"] is False

    # Now component can be made private since project is private
    response = client.patch(
        component_uri,
        json.dumps({"is_public": False}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200, f"Failed for component: {response.content}"
    assert response.json()["is_public"] is False

    # Test making them public again (reverse order)
    response = client.patch(
        component_uri,
        json.dumps({"is_public": True}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    response = client.patch(
        project_uri,
        json.dumps({"is_public": True}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    response = client.patch(
        product_uri,
        json.dumps({"is_public": True}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 200
    assert response.json()["is_public"] is True

    # Test 4: Workspaces without billing plan cannot make items private
    team.billing_plan = None
    team.save()
    product = Product.objects.get(pk=sample_product.id)
    project = Project.objects.get(pk=sample_project.id)
    component = Component.objects.get(pk=sample_component.id)

    # Need to handle hierarchy constraints: make product private first, then project, then component
    # Product cannot be made private
    response = client.patch(
        product_uri,
        json.dumps({"is_public": False}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 403
    assert "cannot make items private" in response.json()["detail"]
    product.refresh_from_db()
    assert product.is_public is True

    # Project cannot be made private
    response = client.patch(
        project_uri,
        json.dumps({"is_public": False}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 403
    assert "cannot make items private" in response.json()["detail"]
    project.refresh_from_db()
    assert project.is_public is True

    # Component cannot be made private
    response = client.patch(
        component_uri,
        json.dumps({"is_public": False}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )
    assert response.status_code == 403
    assert "cannot make items private" in response.json()["detail"]
    component.refresh_from_db()
    assert component.is_public is True


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

    component_uri = reverse("api-1:patch_component", kwargs={"component_id": sample_component.id})

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
def test_community_plan_restriction_bypassed_when_billing_disabled(sample_component, sample_access_token):  # noqa: F811
    """Test that public status restrictions are bypassed when billing is disabled."""
    client = Client()

    # Make component public
    url = reverse("api-1:patch_component", kwargs={"component_id": sample_component.id})
    response = client.patch(
        url,
        json.dumps({"is_public": True}),
        content_type="application/json",
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    assert response.json()["is_public"] is True


@pytest.mark.django_db
def test_download_sbom_public_success(
    client: Client,
    sample_team_with_owner_member,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test successful public SBOM download without authentication."""
    # Create a public SBOM component
    public_component = Component.objects.create(
        name="Public SBOM Component",
        team=sample_team_with_owner_member.team,
        component_type=Component.ComponentType.SBOM,
        is_public=True,
    )

    public_sbom = SBOM.objects.create(
        name="Public SBOM",
        version="1.0",
        sbom_filename="public_sbom.json",
        component=public_component,
        source="manual_upload",
        format="cyclonedx",
        format_version="1.6",
    )

    # Mock S3 client
    mock_get_sbom_data = mocker.patch("sbomify.apps.core.object_store.S3Client.get_sbom_data")
    mock_get_sbom_data.return_value = b'{"name": "public sbom content"}'

    response = client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": public_sbom.id}))

    assert response.status_code == 200
    assert response.content == b'{"name": "public sbom content"}'
    assert response["Content-Type"] == "application/json"
    assert f'attachment; filename="{public_sbom.name}.json"' in response["Content-Disposition"]


@pytest.mark.django_db
def test_download_sbom_private_success(
    client: Client,
    sample_user,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test successful private SBOM download with authentication."""
    # Mock S3 client
    mock_get_sbom_data = mocker.patch("sbomify.apps.core.object_store.S3Client.get_sbom_data")
    mock_get_sbom_data.return_value = b'{"name": "private sbom content"}'

    # Set up session with team access
    setup_test_session(client, sample_sbom.component.team, sample_sbom.component.team.members.first())

    response = client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": sample_sbom.id}))

    assert response.status_code == 200
    assert response.content == b'{"name": "private sbom content"}'
    assert response["Content-Type"] == "application/json"
    assert f'attachment; filename="{sample_sbom.name}.json"' in response["Content-Disposition"]


@pytest.mark.django_db
def test_download_sbom_private_forbidden(
    client: Client,
    sample_sbom: SBOM,  # noqa: F811
):
    """Test that private SBOMs cannot be downloaded without authentication."""
    response = client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": sample_sbom.id}))

    assert response.status_code == 403
    data = response.json()
    assert "Access denied" in data["detail"]


@pytest.mark.django_db
def test_download_sbom_not_found(
    client: Client,
):
    """Test downloading non-existent SBOM."""
    response = client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": "non-existent"}))

    assert response.status_code == 404
    data = response.json()
    assert "SBOM not found" in data["detail"]


@pytest.mark.django_db
def test_download_sbom_file_not_found(
    client: Client,
    sample_user,  # noqa: F811
    sample_component: Component,  # noqa: F811
):
    """Test download when SBOM has no filename."""
    # Create SBOM without filename
    sbom = SBOM.objects.create(
        name="SBOM Without File",
        version="1.0",
        sbom_filename="",  # No filename
        component=sample_component,
        source="manual_upload",
        format="cyclonedx",
        format_version="1.6",
    )

    # Set up session with team access
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    response = client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": sbom.id}))

    assert response.status_code == 404
    data = response.json()
    assert "SBOM file not found" in data["detail"]


@pytest.mark.django_db
def test_download_sbom_s3_file_not_found(
    client: Client,
    sample_user,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test download when S3 file doesn't exist."""
    # Mock S3 client to return None (file not found)
    mock_get_sbom_data = mocker.patch("sbomify.apps.core.object_store.S3Client.get_sbom_data")
    mock_get_sbom_data.return_value = None

    # Set up session with team access
    setup_test_session(client, sample_sbom.component.team, sample_sbom.component.team.members.first())

    response = client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": sample_sbom.id}))

    assert response.status_code == 404
    data = response.json()
    assert "SBOM file not found" in data["detail"]


@pytest.mark.django_db
def test_download_sbom_s3_error(
    client: Client,
    sample_user,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test download handling when S3 raises an error."""
    # Mock S3 client to raise an exception
    mock_get_sbom_data = mocker.patch("sbomify.apps.core.object_store.S3Client.get_sbom_data")
    mock_get_sbom_data.side_effect = Exception("S3 download failed")

    # Set up session with team access
    setup_test_session(client, sample_sbom.component.team, sample_sbom.component.team.members.first())

    response = client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": sample_sbom.id}))

    assert response.status_code == 500
    data = response.json()
    assert "Error retrieving SBOM" in data["detail"]


@pytest.mark.django_db
def test_download_sbom_with_fallback_filename(
    client: Client,
    sample_user,  # noqa: F811
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """Test download with SBOM that has no name (fallback to sbom_id)."""
    # Mock S3 client
    mock_get_sbom_data = mocker.patch("sbomify.apps.core.object_store.S3Client.get_sbom_data")
    mock_get_sbom_data.return_value = b'{"name": "test sbom content"}'

    # Create SBOM with empty name
    sbom = SBOM.objects.create(
        name="",
        version="1.0",
        sbom_filename="test_file.json",
        component=sample_component,
        source="manual_upload",
        format="cyclonedx",
        format_version="1.6",
    )

    # Set up session with team access
    setup_test_session(client, sample_component.team, sample_component.team.members.first())

    response = client.get(reverse("api-1:download_sbom", kwargs={"sbom_id": sbom.id}))

    assert response.status_code == 200
    assert response.content == b'{"name": "test sbom content"}'
    assert f'attachment; filename="sbom_{sbom.id}.json"' in response["Content-Disposition"]
