"""A mistyped field on an SPDX 3 package is absent, not a server fault.

``SPDX3Package`` is the lenient reader, and on a large share of SPDX 3 uploads
it is the only reader: ``spdx3_validation`` holds a document to the vendored
official schema only where it claims a version that has one, so a legacy
``spdxVersion``/``elements`` document, or a bare "3.0" claim, never meets it.

Its fields were typed ``str`` with no coercion, so a package element carrying
``"name": 12345`` raised ``ValidationError`` out of ``SPDX3Schema.packages``.
That is a property, read by ``_extract_spdx3_primary_package`` long after the
upload handler's ``except ValidationError`` guard has gone by, so it landed in
the catch-all: 400 ``{"detail": "Invalid request"}`` for the uploader, naming
nothing they could fix, and an error event for us.

Every field already defaults to "". A value of the wrong type now reads the
same way, and the document is accepted on its merits with the metadata it
actually supplies.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from pytest_mock.plugin import MockerFixture

from ..apis import _extract_spdx3_primary_package
from ..models import SBOM, Component
from ..schemas import SPDX3Package, SPDX3Schema, validate_spdx_sbom
from .fixtures import sample_access_token, sample_component  # noqa: F401
from .test_views import setup_test_session

BARE_30_CONTEXT = "https://spdx.org/rdf/3.0/spdx-context.jsonld"

MISTYPED_PACKAGE: dict[str, Any] = {
    "type": "software_Package",
    "spdxId": "urn:pkg",
    "name": 12345,
    "software_packageVersion": {"not": "a string"},
}


def _legacy_document() -> dict[str, Any]:
    """The shape the vendored schema is never asked about."""
    return {
        "spdxVersion": "SPDX-3.0",
        "elements": [
            {"type": "SpdxDocument", "spdxId": "urn:doc", "name": "doc", "rootElement": ["urn:pkg"]},
            dict(MISTYPED_PACKAGE),
        ],
    }


def _bare_30_document() -> dict[str, Any]:
    """A "3.0" claim names no release to hold it to, so it is accepted leniently."""
    return {
        "@context": BARE_30_CONTEXT,
        "@graph": [
            {"type": "CreationInfo", "specVersion": "3.0"},
            {"type": "SpdxDocument", "spdxId": "urn:doc", "name": "doc", "rootElement": ["urn:pkg"]},
            dict(MISTYPED_PACKAGE),
        ],
    }


class TestPackageFieldTypes:
    def test_a_number_where_a_name_belongs_reads_as_absent(self) -> None:
        package = SPDX3Package.model_validate(MISTYPED_PACKAGE)

        assert package.name == ""
        assert package.version == ""
        assert package.spdx_id == "urn:pkg"

    def test_null_reads_as_absent(self) -> None:
        package = SPDX3Package.model_validate({"type": "software_Package", "spdxId": None, "name": None})

        assert package.name == ""
        assert package.spdx_id == ""

    def test_strings_are_untouched(self) -> None:
        package = SPDX3Package.model_validate(
            {"type": "software_Package", "spdxId": "urn:p1", "name": "libfoo", "software_packageVersion": "9.9.9"}
        )

        assert (package.name, package.version, package.spdx_id) == ("libfoo", "9.9.9", "urn:p1")


class TestDocumentsReachingTheLenientReader:
    @pytest.mark.parametrize("document", [_legacy_document(), _bare_30_document()], ids=["legacy", "bare-3.0"])
    def test_packages_does_not_raise(self, document: dict[str, Any]) -> None:
        payload, _ = validate_spdx_sbom(document)

        assert isinstance(payload, SPDX3Schema)
        assert [(p.name, p.version) for p in payload.packages] == [("", "")]

    def test_primary_package_resolves_through_root_element(self) -> None:
        payload, _ = validate_spdx_sbom(_legacy_document())

        package, error = _extract_spdx3_primary_package(payload)

        assert error == ""
        assert package is not None
        assert package.spdx_id == "urn:pkg"
        assert package.version == ""
        # No name and no external identifier leaves the synthesised fallback,
        # which extract_purl_qualifiers reads without raising.
        assert package.purl == "pkg:/@"


@pytest.mark.django_db
def test_upload_file_accepts_a_legacy_document_with_a_mistyped_package(
    sample_component: Component,  # noqa: F811
    mocker: MockerFixture,  # noqa: F811
):
    """End to end: the path that answered 400 "Invalid request" and reported itself."""
    mocker.patch("boto3.resource")
    mocker.patch("sbomify.apps.core.object_store.StorageClient.upload_data_as_file")
    SBOM.objects.all().delete()

    from django.core.files.uploadedfile import SimpleUploadedFile

    client = Client()
    setup_test_session(client, sample_component.team, sample_component.team.members.first())
    upload = SimpleUploadedFile("doc.json", json.dumps(_legacy_document()).encode(), content_type="application/json")
    resp = client.post(f"/api/v1/sboms/upload-file/{sample_component.id}", {"sbom_file": upload})

    assert resp.status_code == 201, resp.content
    sbom = SBOM.objects.get(id=resp.json()["id"])
    assert sbom.format == "spdx"
    # The stored identifier comes from the SpdxDocument, which is well formed;
    # only the package it roots is not, and that supplies the version.
    assert sbom.name == "doc"
    assert sbom.version == ""
