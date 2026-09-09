"""How an SPDX 2.x document says which package it is about.

``documentDescribes`` is one way. A DESCRIBES relationship from the document
is the other, and the SPDX 2.2 spec treats them as the same statement. Yocto
writes only the relationship, and names the document after the recipe file
rather than after the package, so a reader that knows only the shorthand and a
name match rejects every document a Yocto build produces.
"""

import json

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import SBOM


def _document(**overrides):
    """A minimal SPDX 2.2 document in the shape Yocto emits."""
    doc = {
        "spdxVersion": "SPDX-2.2",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "recipe-openssl",
        "documentNamespace": "http://spdx.org/spdxdocs/recipe-openssl-0f2c1f0e",
        "creationInfo": {
            "created": "2026-01-01T00:00:00Z",
            "creators": ["Tool: OpenEmbedded Core create-spdx.bbclass"],
        },
        "packages": [
            {
                "SPDXID": "SPDXRef-Recipe-openssl",
                "name": "openssl",
                "versionInfo": "3.2.3",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
            }
        ],
    }
    doc.update(overrides)
    return doc


def _upload(client: Client, component: Component, token: AccessToken, document: dict):
    url = reverse("api-1:sbom_upload_spdx", kwargs={"component_id": component.id})
    return client.post(
        url,
        data=json.dumps(document),
        content_type="application/json",
        **get_api_headers(token),
    )


@pytest.mark.django_db
class TestTheDocumentSubject:
    @pytest.fixture(autouse=True)
    def _clean(self, mocker):
        mocker.patch("boto3.resource")
        mocker.patch("sbomify.apps.core.object_store.S3Client.upload_data_as_file")
        SBOM.objects.all().delete()

    def test_a_describes_relationship_names_the_subject(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
    ) -> None:
        """The document name matches no package, so only the relationship can resolve it."""
        document = _document(
            relationships=[
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Recipe-openssl",
                }
            ]
        )

        response = _upload(Client(), sample_component, sample_access_token, document)

        assert response.status_code == 201, response.json()
        assert SBOM.objects.get(id=response.json()["id"]).version == "3.2.3"

    def test_the_relationship_is_read_in_either_direction(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
    ) -> None:
        document = _document(
            relationships=[
                {
                    "spdxElementId": "SPDXRef-Recipe-openssl",
                    "relationshipType": "DESCRIBED_BY",
                    "relatedSpdxElement": "SPDXRef-DOCUMENT",
                }
            ]
        )

        response = _upload(Client(), sample_component, sample_access_token, document)

        assert response.status_code == 201, response.json()
        assert SBOM.objects.get(id=response.json()["id"]).version == "3.2.3"

    def test_the_named_subject_wins_over_the_first_package(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
    ) -> None:
        """Yocto lists the source archive first; the recipe is the one described."""
        document = _document(
            packages=[
                {
                    "SPDXID": "SPDXRef-Download-openssl-1",
                    "name": "openssl-source-1",
                    "versionInfo": "0.0.0",
                    "downloadLocation": "https://example.test/openssl-3.2.3.tar.gz",
                    "filesAnalyzed": False,
                },
                {
                    "SPDXID": "SPDXRef-Recipe-openssl",
                    "name": "openssl",
                    "versionInfo": "3.2.3",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                },
            ],
            relationships=[
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Recipe-openssl",
                }
            ],
        )

        response = _upload(Client(), sample_component, sample_access_token, document)

        assert response.status_code == 201, response.json()
        assert SBOM.objects.get(id=response.json()["id"]).version == "3.2.3"

    def test_the_document_id_is_read_from_the_document(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
    ) -> None:
        """SPDXRef-DOCUMENT is the convention, not a constraint the schema imposes."""
        document = _document(
            SPDXID="SPDXRef-recipe-openssl-doc",
            relationships=[
                {
                    "spdxElementId": "SPDXRef-recipe-openssl-doc",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Recipe-openssl",
                }
            ],
            packages=[
                {
                    "SPDXID": "SPDXRef-Download-openssl-1",
                    "name": "openssl-source-1",
                    "versionInfo": "0.0.0",
                    "downloadLocation": "https://example.test/openssl-3.2.3.tar.gz",
                    "filesAnalyzed": False,
                },
                {
                    "SPDXID": "SPDXRef-Recipe-openssl",
                    "name": "openssl",
                    "versionInfo": "3.2.3",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                },
            ],
        )

        response = _upload(Client(), sample_component, sample_access_token, document)

        assert response.status_code == 201, response.json()
        assert SBOM.objects.get(id=response.json()["id"]).version == "3.2.3"

    def test_a_document_that_names_no_subject_is_still_accepted(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
    ) -> None:
        """The Yocto image document: no documentDescribes, no relationships, no name match."""
        document = _document(
            name="core-image-minimal-qemux86-64.rootfs-20241109141548",
            packages=[
                {
                    "SPDXID": "SPDXRef-Image-core-image-minimal",
                    "name": "core-image-minimal",
                    "versionInfo": "1.0",
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                }
            ],
        )

        response = _upload(Client(), sample_component, sample_access_token, document)

        assert response.status_code == 201, response.json()
        assert SBOM.objects.get(id=response.json()["id"]).version == "1.0"

    @pytest.mark.parametrize(
        "relationships",
        [
            pytest.param([{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES"}], id="no-target"),
            pytest.param(
                [
                    {
                        "spdxElementId": "SPDXRef-DOCUMENT",
                        "relationshipType": "DESCRIBES",
                        "relatedSpdxElement": 42,
                    }
                ],
                id="numeric-target",
            ),
            pytest.param(
                [
                    {
                        "spdxElementId": "SPDXRef-DOCUMENT",
                        "relationshipType": "DESCRIBES",
                        "relatedSpdxElement": {"nested": "object"},
                    }
                ],
                id="object-target",
            ),
            pytest.param(["not a relationship"], id="not-an-object"),
        ],
    )
    def test_a_relationship_that_names_nothing_usable_falls_through(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
        relationships: list,
    ) -> None:
        """Relationships come off the lenient parser as raw dicts, so their
        values are whatever the uploader wrote. None of these is an ID, and
        none of them should reach the ID comparison."""
        document = _document(name="openssl", relationships=relationships)

        response = _upload(Client(), sample_component, sample_access_token, document)

        assert response.status_code == 201, response.json()
        assert SBOM.objects.get(id=response.json()["id"]).version == "3.2.3"

    def test_a_document_with_no_packages_is_still_rejected(
        self,
        sample_access_token: AccessToken,
        sample_component: Component,
    ) -> None:
        """The fallback accepts documents with an inventory, not documents without one."""
        document = _document(packages=[])

        response = _upload(Client(), sample_component, sample_access_token, document)

        assert response.status_code == 400
        assert "No packages found" in response.json()["detail"]
