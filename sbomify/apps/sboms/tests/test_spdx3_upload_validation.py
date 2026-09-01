"""Upload validation for SPDX 3: strict where conformance is claimed, honest
at the edges, lenient where compatibility demands it.

Before this change the SPDX 3 upload check required two keys — ``@context``
and ``@graph`` — with ``extra='allow'``: a document whose graph held
``{"type": "NotARealSpdxType"}`` and made-up properties persisted as
``format_version='3.0.1'`` while the official 259 KB schema sat vendored in
the repo with zero references. And an SPDX 3.1 document missed the 3.0
context match entirely, falling through to the SPDX 2 branch and its
``Invalid spdxVersion format: .`` error for a field SPDX 3 does not have.

The version ladder after this change:

    3.1+        rejected with an error naming what to send instead
    3.0.1+      validated against the vendored official 3.0.1 schema
    3.0 / 3.0.0 accepted leniently (syft, sbom-tool, JFrog still emit it;
                the BSI floor message handles the rest)
    legacy      spdxVersion/elements documents keep today's lenient path
"""

from __future__ import annotations

from typing import Any

import pytest

from sbomify.apps.plugins.tests import spdx3_corpus as corpus
from sbomify.apps.sboms.schemas import validate_spdx_sbom


def _garbage_claiming(spec_version: str) -> dict[str, Any]:
    context_version = "3.0.1" if spec_version.startswith("3.0.1") else spec_version
    return {
        "@context": f"https://spdx.org/rdf/{context_version}/spdx-context.jsonld",
        "@graph": [
            {
                "type": "CreationInfo",
                "@id": "_:ci",
                "specVersion": spec_version,
                "created": "2026-08-01T00:00:00Z",
                "createdBy": ["urn:x:agent"],
            },
            {"type": "software_Package", "name": "x", "totally_made_up": 123},
            {"type": "NotARealSpdxType"},
        ],
    }


class TestStrictWhereConformanceIsClaimed:
    def test_made_up_properties_are_rejected_with_a_pointer(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            validate_spdx_sbom(_garbage_claiming("3.0.1"))

        message = str(excinfo.value)
        assert "schema" in message.lower()
        assert "totally_made_up" in message or "NotARealSpdxType" in message or "@graph/1" in message

    def test_a_conformant_document_passes(self) -> None:
        payload, version = validate_spdx_sbom(corpus.minimal_conformant())

        assert version == "3.0.1"
        assert payload.packages

    def test_a_conformant_3_0_2_document_passes(self) -> None:
        """The floor is '3.0.1 or higher': a formatting-only patch release is
        model-identical and must validate against the 3.0.1 schema rather
        than being exact-match rejected."""
        document = corpus.minimal_conformant()
        for element in document["@graph"]:
            if element["type"] == "CreationInfo":
                element["specVersion"] = "3.0.2"

        payload, version = validate_spdx_sbom(document)

        assert version == "3.0.2"
        assert payload.packages


class TestHonestAtTheEdges:
    def test_spdx_3_1_gets_a_clear_rejection(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            validate_spdx_sbom(corpus.spdx_3_1())

        message = str(excinfo.value)
        assert "3.1" in message
        assert "3.0.1" in message
        assert "Invalid spdxVersion format" not in message

    def test_the_old_garbled_error_is_gone_for_context_only_3_1(self) -> None:
        """A 3.1 document has no root spdxVersion; the old code fell through
        to the SPDX 2 branch and complained about a field SPDX 3 lacks."""
        document = corpus.spdx_3_1()
        with pytest.raises(ValueError) as excinfo:
            validate_spdx_sbom(document)

        assert "Expected format: SPDX-X.X" not in str(excinfo.value)


class TestLenientWhereCompatibilityDemands:
    def test_3_0_0_garbage_is_still_accepted(self) -> None:
        """syft, sbom-tool and JFrog emit 3.0; there is no vendored 3.0.0
        schema to hold them to, and rejecting them would break every one of
        those producers. The BSI floor message covers the version story."""
        payload, version = validate_spdx_sbom(_garbage_claiming("3.0.0"))

        assert version == "3.0.0"

    def test_syft_shaped_document_is_accepted(self) -> None:
        payload, version = validate_spdx_sbom(corpus.syft_shaped())

        assert version == "3.0.0"

    def test_legacy_elements_document_keeps_its_lenient_path(self) -> None:
        document = {
            "spdxVersion": "SPDX-3.0",
            "elements": [
                {"type": "CreationInfo", "specVersion": "3.0.1", "created": "2026-08-01T00:00:00Z"},
                {"type": "software_Package", "name": "p", "made_up_key": True},
            ],
        }

        payload, version = validate_spdx_sbom(document)

        assert version.startswith("3.0")

    def test_spdx_2_3_is_untouched(self) -> None:
        document = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "name": "example",
            "creationInfo": {"created": "2026-08-01T00:00:00Z", "creators": ["Tool: syft-1.0.0"]},
            "packages": [{"SPDXID": "SPDXRef-p", "name": "p", "downloadLocation": "NOASSERTION"}],
        }

        payload, version = validate_spdx_sbom(document)

        assert version == "2.3"


class TestBoundedValidation:
    """Schema validation is O(elements) at roughly 9 ms each — unbounded, a
    Yocto-scale graph (tens of thousands of elements) would hold the upload
    request for minutes and a document near the 100 MB cap for ~20. The
    validator therefore checks at most its cap of elements; a conformance
    claim is still tested, just not exhaustively on huge documents."""

    def _doc_with_garbage_at(self, index: int, total: int) -> dict:
        graph: list[dict] = [
            {
                "type": "CreationInfo",
                "@id": "_:ci",
                "specVersion": "3.0.1",
                "created": "2026-08-01T00:00:00Z",
                "createdBy": ["urn:x:org"],
            },
            {"type": "Organization", "spdxId": "urn:x:org", "creationInfo": "_:ci", "name": "X"},
        ]
        for i in range(total):
            graph.append(
                {
                    "type": "software_Package",
                    "spdxId": f"urn:x:p{i}",
                    "creationInfo": "_:ci",
                    "name": f"p{i}",
                }
            )
        graph[index] = {"type": "NotARealSpdxType", "junk": True}
        return {"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": graph}

    def test_garbage_inside_the_cap_is_still_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_spdx_sbom(self._doc_with_garbage_at(index=5, total=700))

    def test_garbage_beyond_the_cap_is_accepted_by_design(self) -> None:
        """The documented ceiling: elements past the cap go unchecked rather
        than holding the request for minutes."""
        from sbomify.apps.sboms.spdx3_validation import MAX_VALIDATED_ELEMENTS

        payload, version = validate_spdx_sbom(
            self._doc_with_garbage_at(index=MAX_VALIDATED_ELEMENTS + 50, total=MAX_VALIDATED_ELEMENTS + 100)
        )

        assert version == "3.0.1"
