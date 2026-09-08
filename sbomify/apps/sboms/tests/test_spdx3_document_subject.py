"""Which package an SPDX 3 document is about, when it roots itself on its Sbom.

SPDX 3 lets a document point rootElement at the Sbom rather than straight at
the thing the Sbom describes, and Yocto does exactly that: SpdxDocument
rootElement names a software_Sbom, and that element's own rootElement names the
image. Reading only the first hop found no package and fell through to "take
the first one", which labelled a whole OS image with the version of whichever
recipe happened to serialise first.
"""

from __future__ import annotations

from typing import Any

from sbomify.apps.sboms.apis import _extract_spdx_primary_package
from sbomify.apps.sboms.schemas import validate_spdx_sbom

DOC = "https://example.test/spdxdocs/image"
SBOM_ID = "https://example.test/spdxdocs/image/sbom"
IMAGE = "https://example.test/spdxdocs/image/rootfs/core-image-minimal"
DECOY = "https://example.test/spdxdocs/acl/package/acl"


AGENT = "https://example.test/agent/openembedded"


def _document(*, root: str, sbom_root: str | None = None) -> dict[str, Any]:
    graph: list[dict[str, Any]] = [
        {
            "type": "CreationInfo",
            "@id": "_:c1",
            "specVersion": "3.0.1",
            "created": "2026-08-19T09:11:34Z",
            "createdBy": [AGENT],
        },
        {"type": "Organization", "spdxId": AGENT, "creationInfo": "_:c1", "name": "OpenEmbedded"},
        {
            "type": "SpdxDocument",
            "spdxId": DOC,
            "creationInfo": "_:c1",
            "name": "core-image-minimal-qemux86-64.rootfs-20260819091134",
            "rootElement": [root],
        },
        # Serialised first, exactly as Yocto orders it, so a first-package
        # fallback picks this one.
        {
            "type": "software_Package",
            "spdxId": DECOY,
            "creationInfo": "_:c1",
            "name": "acl",
            "software_packageVersion": "2.3.2",
        },
        {
            "type": "software_Package",
            "spdxId": IMAGE,
            "creationInfo": "_:c1",
            "name": "core-image-minimal",
            "software_packageVersion": "1.0",
        },
    ]
    if sbom_root is not None:
        graph.append(
            {
                "type": "software_Sbom",
                "spdxId": SBOM_ID,
                "creationInfo": "_:c1",
                "software_sbomType": ["build"],
                "rootElement": [sbom_root],
            }
        )
    return {"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": graph}


def _primary(document: dict[str, Any]):
    payload, _ = validate_spdx_sbom(document)
    package, error = _extract_spdx_primary_package(payload)
    assert error == "", error
    return package


class TestTheDeclaredSubject:
    def test_a_document_rooted_on_its_sbom_resolves_through_it(self) -> None:
        package = _primary(_document(root=SBOM_ID, sbom_root=IMAGE))

        assert package.name == "core-image-minimal"

    def test_a_document_rooted_straight_on_the_package_still_works(self) -> None:
        package = _primary(_document(root=IMAGE))

        assert package.name == "core-image-minimal"

    def test_an_sbom_root_pointing_at_nothing_falls_through(self) -> None:
        """Still returns a package, just not one the document managed to name."""
        package = _primary(_document(root=SBOM_ID, sbom_root="https://example.test/nothing-here"))

        assert package is not None

    def test_a_root_that_is_not_an_sbom_at_all_is_not_followed(self) -> None:
        """The document roots on something that is neither package nor Sbom."""
        package = _primary(_document(root=AGENT))

        assert package is not None

    def test_an_sbom_the_document_does_not_root_on_is_not_followed(self) -> None:
        """Only the Sbom the document points at gets resolved, not every Sbom
        in the graph."""
        document = _document(root=IMAGE, sbom_root=DECOY)

        assert _primary(document).name == "core-image-minimal"
