"""Upload validation for SPDX 3: strict where conformance is claimed, honest
at the edges, lenient where compatibility demands it.

Before this change the SPDX 3 upload check required two keys — ``@context``
and ``@graph`` — with ``extra='allow'``: a document whose graph held
``{"type": "NotARealSpdxType"}`` and made-up properties persisted as
``format_version='3.0.1'`` while the official 259 KB schema sat vendored in
the repo with zero references. And an SPDX 3.1 document missed the 3.0
context match entirely, falling through to the SPDX 2 branch and its
``Invalid spdxVersion format: .`` error for a field SPDX 3 does not have.

The version ladder, now that 3.0.0 has a vendored schema too:

    3.1+        rejected with an error naming what to send instead
    3.0.1+      validated against the vendored official 3.0.1 schema
    3.0.0       validated against the vendored official 3.0.0 schema
    3.0         a bare line, as Microsoft sbom-tool writes it, names no release
                to hold it to: accepted leniently
    alias       a 3.0.0 claim under the unversioned spdx.org/rdf/3.0/ context
                keeps the leniency every 3.0.0 claim had before
    legacy      spdxVersion/elements documents keep today's lenient path
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sbomify.apps.plugins.tests import spdx3_corpus as corpus
from sbomify.apps.sboms.schemas import validate_spdx_sbom

YOCTO_5_1 = Path(__file__).resolve().parent / "test_data" / "yocto_core-image-minimal.spdx3.0.0.json"
UNVERSIONED_CONTEXT = "https://spdx.org/rdf/3.0/spdx-context.jsonld"


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

    def test_a_conformant_3_0_0_document_passes(self) -> None:
        payload, version = validate_spdx_sbom(corpus.spdx_3_0_0())

        assert version == "3.0.0"
        assert payload.packages

    def test_a_syft_shaped_3_0_0_document_passes(self) -> None:
        payload, version = validate_spdx_sbom(corpus.syft_shaped())

        assert version == "3.0.0"

    def test_3_0_0_garbage_is_rejected_with_a_pointer(self) -> None:
        """Accepted unchecked until 3.0.0 had a schema of its own."""
        with pytest.raises(ValueError) as excinfo:
            validate_spdx_sbom(_garbage_claiming("3.0.0"))

        message = str(excinfo.value)
        assert "failed 3.0.0 schema validation" in message
        assert "/@graph/1" in message
        assert "{'@context'" not in message

    def test_a_3_0_0_claim_is_held_to_the_3_0_0_context(self) -> None:
        document = corpus.spdx_3_0_0()
        document["@context"] = corpus.CONTEXT

        with pytest.raises(ValueError, match="/@context"):
            validate_spdx_sbom(document)

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


def _with_property(version: str, element_type: str, prop: str) -> dict[str, Any]:
    """A conformant document claiming ``version``, with ``prop`` set on an
    element of ``element_type``."""
    document = corpus.spdx_3_0_0() if version == "3.0.0" else corpus.minimal_conformant()
    values: dict[str, Any] = {
        "software_File": "text/plain",
        "SpdxDocument": [{"type": "ExternalMap", "externalSpdxId": "urn:other:doc"}],
        "build_Build": [{"type": "DictionaryEntry", "key": "target", "value": "x86_64"}],
    }
    if element_type == "SpdxDocument":
        element = next(e for e in document["@graph"] if e["type"] == "SpdxDocument")
    else:
        element = {"type": element_type, "spdxId": "urn:acme:extra", "creationInfo": "_:creationinfo"}
        if element_type == "build_Build":
            element["build_buildType"] = "https://acme.test/build"
        document["@graph"].append(element)
    element[prop] = values[element_type]
    return document


RENAMED_IN_3_0_1 = [
    ("software_File", "software_contentType", "contentType"),
    ("SpdxDocument", "imports", "import"),
    ("build_Build", "build_parameters", "build_parameter"),
]


@pytest.mark.parametrize(("element_type", "spelling_3_0_0", "spelling_3_0_1"), RENAMED_IN_3_0_1)
class TestTheTwoSchemasDisagree:
    """3.0.1 renamed three properties 3.0.0 defines. Each claim takes its own
    version's spelling and refuses the other's, which is why one schema cannot
    stand in for both."""

    def test_3_0_0_takes_its_own_spelling(self, element_type: str, spelling_3_0_0: str, spelling_3_0_1: str) -> None:
        _payload, version = validate_spdx_sbom(_with_property("3.0.0", element_type, spelling_3_0_0))

        assert version == "3.0.0"

    def test_3_0_0_refuses_the_3_0_1_spelling(
        self, element_type: str, spelling_3_0_0: str, spelling_3_0_1: str
    ) -> None:
        with pytest.raises(ValueError, match=f"'{spelling_3_0_1}' was unexpected"):
            validate_spdx_sbom(_with_property("3.0.0", element_type, spelling_3_0_1))

    def test_3_0_1_takes_its_own_spelling(self, element_type: str, spelling_3_0_0: str, spelling_3_0_1: str) -> None:
        _payload, version = validate_spdx_sbom(_with_property("3.0.1", element_type, spelling_3_0_1))

        assert version == "3.0.1"

    def test_3_0_1_refuses_the_3_0_0_spelling(
        self, element_type: str, spelling_3_0_0: str, spelling_3_0_1: str
    ) -> None:
        with pytest.raises(ValueError, match=f"'{spelling_3_0_0}' was unexpected"):
            validate_spdx_sbom(_with_property("3.0.1", element_type, spelling_3_0_0))


class TestIndividualElementIsNew:
    INDIVIDUAL = {"type": "IndividualElement", "spdxId": "urn:acme:individual", "creationInfo": "_:creationinfo"}

    def test_3_0_1_takes_an_individual_element(self) -> None:
        document = corpus.minimal_conformant()
        document["@graph"].append(dict(self.INDIVIDUAL))

        _payload, version = validate_spdx_sbom(document)

        assert version == "3.0.1"

    def test_3_0_0_refuses_one(self) -> None:
        document = corpus.spdx_3_0_0()
        document["@graph"].append(dict(self.INDIVIDUAL))

        with pytest.raises(ValueError, match="failed 3.0.0 schema validation"):
            validate_spdx_sbom(document)


class TestRealProducerOutput:
    def test_published_yocto_5_1_output_passes(self) -> None:
        """Yocto 5.1 writes SPDX 3.0.0. Its published core-image-minimal SBOM
        validates against the 3.0.0 schema, all 2066 elements of it; the upload
        checks the first 500."""
        _payload, version = validate_spdx_sbom(json.loads(YOCTO_5_1.read_text()))

        assert version == "3.0.0"

    def test_and_it_is_checked_rather_than_waved_through(self) -> None:
        document = json.loads(YOCTO_5_1.read_text())
        spdx_document = next(e for e in document["@graph"] if e["type"] == "SpdxDocument")
        spdx_document["totally_made_up"] = 1

        with pytest.raises(ValueError, match="totally_made_up"):
            validate_spdx_sbom(document)


class TestLenientWhereCompatibilityDemands:
    def test_a_bare_3_0_claim_stays_lenient(self) -> None:
        """Microsoft sbom-tool writes ``specVersion: "3.0"`` under a context
        list naming 3.0.1. "3.0" names no release, so no schema can hold it."""
        document = _garbage_claiming("3.0")
        document["@context"] = ["https://spdx.org/rdf/3.0.1/spdx-context.json"]

        _payload, version = validate_spdx_sbom(document)

        assert version == "3.0"

    def test_a_3_0_0_claim_under_the_unversioned_alias_stays_lenient(self) -> None:
        """Both schemas pin a versioned ``@context``, so the alias validates
        against neither. Such a claim keeps the leniency it had before 3.0.0
        was checked, until someone decides how strict to be with the alias."""
        document = _garbage_claiming("3.0.0")
        document["@context"] = UNVERSIONED_CONTEXT

        _payload, version = validate_spdx_sbom(document)

        assert version == "3.0.0"

    def test_the_alias_counts_inside_a_context_list(self) -> None:
        document = _garbage_claiming("3.0.0")
        document["@context"] = [{"@vocab": "https://spdx.org/rdf/3.0/terms/"}]

        _payload, version = validate_spdx_sbom(document)

        assert version == "3.0.0"

    def test_a_3_0_1_claim_under_the_alias_is_still_refused(self) -> None:
        """It already was: the 3.0.1 schema pins its own ``@context``. Pinned
        so the alias leniency above does not quietly spread to 3.0.1."""
        document = corpus.minimal_conformant()
        document["@context"] = UNVERSIONED_CONTEXT

        with pytest.raises(ValueError, match="/@context"):
            validate_spdx_sbom(document)

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
