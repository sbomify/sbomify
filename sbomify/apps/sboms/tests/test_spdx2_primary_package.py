"""The component a release aggregate names for an SPDX 2 member is the package the member describes.

The builder read ``documentDescribes`` and otherwise took ``packages[0]``. A
document that states its subject as a DESCRIBES relationship, the only form
Yocto writes, was named after whichever package happened to come first.
"""

from __future__ import annotations

from typing import Any

import pytest

from sbomify.apps.sboms.builders import ReleaseSPDX23Builder


def _doc(**extra: Any) -> dict[str, Any]:
    return {
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "packages": [
            {"SPDXID": "SPDXRef-source", "name": "libfoo-source", "versionInfo": "9.9.9"},
            {"SPDXID": "SPDXRef-app", "name": "my-app", "versionInfo": "1.2.3", "supplier": "Organization: Acme"},
        ],
        **extra,
    }


def _describes(target: str) -> dict[str, str]:
    return {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": target}


def _name_of(document: dict[str, Any]) -> str | None:
    info = ReleaseSPDX23Builder()._extract_component_info_from_sbom(document, "member.json")
    return info[0] if info else None


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        pytest.param({"relationships": [_describes("SPDXRef-app")]}, "my-app", id="describes-relationship-only"),
        pytest.param({"documentDescribes": ["SPDXRef-app"]}, "my-app", id="document-describes-shorthand"),
        pytest.param(
            {"documentDescribes": ["SPDXRef-app"], "relationships": [_describes("SPDXRef-source")]},
            "my-app",
            id="shorthand-wins-over-relationship",
        ),
        pytest.param({"relationships": [_describes("SPDXRef-missing")]}, "libfoo-source", id="dangling-target"),
        pytest.param({}, "libfoo-source", id="nothing-declared"),
        pytest.param(
            {"packages": [{"SPDXID": "SPDXRef-a", "name": "first"}, {"name": "no-id"}]},
            "first",
            id="package-without-an-id-is-not-the-subject",
        ),
    ],
)
def test_names_the_package_the_document_describes(extra: dict[str, Any], expected: str) -> None:
    assert _name_of(_doc(**extra)) == expected


def test_reads_version_and_supplier_from_the_described_package() -> None:
    info = ReleaseSPDX23Builder()._extract_component_info_from_sbom(
        _doc(relationships=[_describes("SPDXRef-app")]), "member.json"
    )

    assert info == ("my-app", "1.2.3", "Organization: Acme")
