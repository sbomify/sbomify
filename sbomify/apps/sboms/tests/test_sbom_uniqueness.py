"""Tests for SBOM uniqueness constraint.

The uniqueness constraint ensures that the combination of
(component, version, format) is unique. This prevents duplicate
SBOM uploads while allowing:
- Same version with different format (CycloneDX vs SPDX)
- Different versions with same format
"""

from __future__ import annotations

import json
from io import BytesIO

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import SBOM, Component, Project


class TestSBOMUniquenessConstraintCycloneDX:
    """Tests for CycloneDX SBOM uniqueness."""

    @pytest.mark.django_db
    def test_duplicate_returns_409(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that uploading a duplicate CycloneDX SBOM returns 409 Conflict."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component", "version": "1.0.0"}},
        }

        client = Client()
        url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})

        # First upload should succeed
        response = client.post(
            url,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201
        first_sbom_id = response.json()["id"]

        # Second upload with same version + format should return 409
        response = client.post(
            url,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]
        assert "1.0.0" in response.json()["detail"]
        assert "cyclonedx" in response.json()["detail"]
        assert response.json()["error_code"] == "DUPLICATE_ARTIFACT"

        # Verify only one SBOM was created
        assert SBOM.objects.count() == 1
        assert SBOM.objects.filter(id=first_sbom_id).exists()

    @pytest.mark.django_db
    def test_different_version_succeeds(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that uploading CycloneDX SBOM with different version succeeds."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        client = Client()
        url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})

        # Upload version 1.0.0
        sbom_data_v1 = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component", "version": "1.0.0"}},
        }
        response = client.post(
            url,
            data=json.dumps(sbom_data_v1),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Upload version 2.0.0 - should succeed
        sbom_data_v2 = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component", "version": "2.0.0"}},
        }
        response = client.post(
            url,
            data=json.dumps(sbom_data_v2),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Upload version 3.0.0-beta - should also succeed
        sbom_data_v3 = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component", "version": "3.0.0-beta"}},
        }
        response = client.post(
            url,
            data=json.dumps(sbom_data_v3),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        assert SBOM.objects.count() == 3
        assert SBOM.objects.filter(version="1.0.0").exists()
        assert SBOM.objects.filter(version="2.0.0").exists()
        assert SBOM.objects.filter(version="3.0.0-beta").exists()

    @pytest.mark.django_db
    def test_empty_version_duplicate_returns_409(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that uploading duplicate SBOMs with empty versions returns 409."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        # CycloneDX without version in component
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component"}},
        }

        client = Client()
        url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})

        # First upload should succeed
        response = client.post(
            url,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Verify empty version was stored
        sbom = SBOM.objects.first()
        assert sbom is not None
        assert sbom.version == ""

        # Second upload with same empty version should return 409
        response = client.post(
            url,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]


class TestSBOMUniquenessConstraintSPDX:
    """Tests for SPDX SBOM uniqueness."""

    @pytest.mark.django_db
    def test_duplicate_returns_409(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that uploading a duplicate SPDX SBOM returns 409 Conflict."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        spdx_data = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "spdxVersion": "SPDX-2.3",
            "creationInfo": {
                "created": "2024-06-06T07:48:34Z",
                "creators": ["Tool: Test"],
            },
            "name": "test-component",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "documentDescribes": ["SPDXRef-Package"],
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "test-component",
                    "versionInfo": "1.0.0",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                }
            ],
        }

        client = Client()
        url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})

        # First upload should succeed
        response = client.post(
            url,
            data=json.dumps(spdx_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Second upload with same version + format should return 409
        response = client.post(
            url,
            data=json.dumps(spdx_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]
        assert "1.0.0" in response.json()["detail"]
        assert "spdx" in response.json()["detail"]
        assert response.json()["error_code"] == "DUPLICATE_ARTIFACT"

    @pytest.mark.django_db
    def test_different_version_succeeds(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that uploading SPDX SBOM with different version succeeds."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        client = Client()
        url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})

        def create_spdx_data(version: str) -> dict:
            return {
                "SPDXID": "SPDXRef-DOCUMENT",
                "spdxVersion": "SPDX-2.3",
                "creationInfo": {
                    "created": "2024-06-06T07:48:34Z",
                    "creators": ["Tool: Test"],
                },
                "name": "test-component",
                "dataLicense": "CC0-1.0",
                "documentNamespace": f"https://example.com/test-{version}",
                "documentDescribes": ["SPDXRef-Package"],
                "packages": [
                    {
                        "SPDXID": "SPDXRef-Package",
                        "name": "test-component",
                        "versionInfo": version,
                        "downloadLocation": "NOASSERTION",
                        "filesAnalyzed": False,
                    }
                ],
            }

        # Upload multiple versions
        for version in ["1.0.0", "1.1.0", "2.0.0"]:
            response = client.post(
                url,
                data=json.dumps(create_spdx_data(version)),
                content_type="application/json",
                **get_api_headers(sample_access_token),
            )
            assert response.status_code == 201

        assert SBOM.objects.count() == 3
        assert SBOM.objects.filter(format="spdx").count() == 3

    @pytest.mark.django_db
    def test_empty_version_duplicate_returns_409(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that uploading duplicate SPDX SBOMs with empty versionInfo returns 409.

        In SPDX, versionInfo is optional. When not provided, it defaults to empty string.
        Two SBOMs with no versionInfo should still be considered duplicates.
        """
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        # SPDX without versionInfo in the package
        spdx_data = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "spdxVersion": "SPDX-2.3",
            "creationInfo": {
                "created": "2024-06-06T07:48:34Z",
                "creators": ["Tool: Test"],
            },
            "name": "test-component",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "documentDescribes": ["SPDXRef-Package"],
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "test-component",
                    # versionInfo intentionally omitted
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                }
            ],
        }

        client = Client()
        url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})

        # First upload should succeed
        response = client.post(
            url,
            data=json.dumps(spdx_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Verify empty version was stored
        sbom = SBOM.objects.first()
        assert sbom is not None
        assert sbom.version == ""

        # Second upload with same empty version should return 409
        response = client.post(
            url,
            data=json.dumps(spdx_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]


class TestSBOMUniquenessConstraintCrossFormat:
    """Tests for cross-format SBOM uniqueness."""

    @pytest.mark.django_db
    def test_same_version_different_format_succeeds(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that uploading SBOM with same version but different format succeeds."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        client = Client()

        # Upload CycloneDX version 1.0.0
        cyclonedx_url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})
        cyclonedx_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component", "version": "1.0.0"}},
        }
        response = client.post(
            cyclonedx_url,
            data=json.dumps(cyclonedx_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Upload SPDX version 1.0.0 - should succeed (different format)
        spdx_url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": sample_component.id})
        spdx_data = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "spdxVersion": "SPDX-2.3",
            "creationInfo": {
                "created": "2024-06-06T07:48:34Z",
                "creators": ["Tool: Test"],
            },
            "name": "test-component",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "documentDescribes": ["SPDXRef-Package"],
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "test-component",
                    "versionInfo": "1.0.0",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                }
            ],
        }
        response = client.post(
            spdx_url,
            data=json.dumps(spdx_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        assert SBOM.objects.count() == 2
        assert SBOM.objects.filter(format="cyclonedx", version="1.0.0").count() == 1
        assert SBOM.objects.filter(format="spdx", version="1.0.0").count() == 1

    @pytest.mark.django_db
    def test_different_components_same_version_succeeds(
        self,
        sample_access_token: AccessToken,
        sample_project: Project,
        mocker: MockerFixture,
    ) -> None:
        """Test that same version can be uploaded to different components."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        # Create two components
        component1 = Component.objects.create(
            name="component-1",
            team_id=sample_project.team_id,
        )
        component2 = Component.objects.create(
            name="component-2",
            team_id=sample_project.team_id,
        )

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component", "version": "1.0.0"}},
        }

        client = Client()

        # Upload to component1
        url1 = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": component1.id})
        response = client.post(
            url1,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Upload same version to component2 - should succeed
        url2 = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": component2.id})
        response = client.post(
            url2,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        assert SBOM.objects.count() == 2
        assert SBOM.objects.filter(component=component1).count() == 1
        assert SBOM.objects.filter(component=component2).count() == 1

        # Cleanup
        component1.delete()
        component2.delete()


class TestSBOMUniquenessConstraintFileUpload:
    """Tests for file upload endpoint uniqueness."""

    @pytest.mark.django_db
    def test_cyclonedx_duplicate_returns_409(
        self,
        sample_user,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that file upload of duplicate CycloneDX SBOM returns 409 Conflict."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        cyclonedx_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component", "version": "1.0.0"}},
        }

        client = Client()
        client.force_login(sample_user)

        url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id})

        file_content = json.dumps(cyclonedx_data).encode("utf-8")

        # First upload should succeed
        response = client.post(
            url,
            data={"sbom_file": BytesIO(file_content)},
            format="multipart",
        )
        assert response.status_code == 201

        # Second upload with same version + format should return 409
        response = client.post(
            url,
            data={"sbom_file": BytesIO(file_content)},
            format="multipart",
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]
        assert response.json()["error_code"] == "DUPLICATE_ARTIFACT"

    @pytest.mark.django_db
    def test_spdx_duplicate_returns_409(
        self,
        sample_user,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that file upload of duplicate SPDX SBOM returns 409 Conflict."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        spdx_data = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "spdxVersion": "SPDX-2.3",
            "creationInfo": {
                "created": "2024-06-06T07:48:34Z",
                "creators": ["Tool: Test"],
            },
            "name": "test-component",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "documentDescribes": ["SPDXRef-Package"],
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "test-component",
                    "versionInfo": "2.0.0",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                }
            ],
        }

        client = Client()
        client.force_login(sample_user)

        url = reverse("api-1:sbom_upload_file", kwargs={"component_id": sample_component.id})

        file_content = json.dumps(spdx_data).encode("utf-8")

        # First upload should succeed
        response = client.post(
            url,
            data={"sbom_file": BytesIO(file_content)},
            format="multipart",
        )
        assert response.status_code == 201

        # Second upload should return 409
        response = client.post(
            url,
            data={"sbom_file": BytesIO(file_content)},
            format="multipart",
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]
        assert response.json()["error_code"] == "DUPLICATE_ARTIFACT"


class TestSBOMUniquenessConstraintErrorHandling:
    """Tests for error handling and edge cases."""

    @pytest.mark.django_db
    def test_error_message_contains_details(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that the 409 error message contains version and format details."""
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component", "version": "5.2.1"}},
        }

        client = Client()
        url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})

        # First upload
        response = client.post(
            url,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201

        # Second upload - check error details
        response = client.post(
            url,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 409
        error_detail = response.json()["detail"]
        assert "5.2.1" in error_detail
        assert "cyclonedx" in error_detail
        assert "already exists" in error_detail
        assert response.json()["error_code"] == "DUPLICATE_ARTIFACT"

    @pytest.mark.django_db
    def test_duplicate_does_not_upload_to_s3(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        mocker: MockerFixture,
    ) -> None:
        """Test that duplicate uploads do not upload files to S3."""
        mocker.patch("boto3.resource")
        mock_upload = mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")

        SBOM.objects.all().delete()

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {"component": {"type": "application", "name": "test-component", "version": "1.0.0"}},
        }

        client = Client()
        url = reverse("api-1:sbom_upload_cyclonedx", kwargs={"component_id": sample_component.id})

        # First upload - should call S3
        response = client.post(
            url,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 201
        assert mock_upload.call_count == 1

        # Second upload - should NOT call S3 (rejected before upload)
        response = client.post(
            url,
            data=json.dumps(sbom_data),
            content_type="application/json",
            **get_api_headers(sample_access_token),
        )
        assert response.status_code == 409
        assert mock_upload.call_count == 1  # Still 1, not 2
