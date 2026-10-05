"""The BOM subject of an SPDX 3 document is declared by rootElement.

The primary-package pickers looked for a ``describes`` Relationship (an
SPDX 2 idiom), then a name match, then fell back to ``packages[0]`` — and
never read ``rootElement``. A three-package document whose SpdxDocument
declares ``rootElement: ['urn:p3']`` stored the first package's name and
version, and the release aggregate named the component after the wrong
package.

The fallbacks stay: a document with no rootElement and a ``describes``
relationship keeps today's behaviour, and one with neither still resolves to
the first package without raising.
"""

from __future__ import annotations

from typing import Any

from sbomify.apps.sboms.apis import _extract_spdx3_primary_package
from sbomify.apps.sboms.builders import _spdx3_component_info
from sbomify.apps.sboms.schemas import SPDX3Package, SPDX3Schema

CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"


def _doc(*graph: dict[str, Any]) -> dict[str, Any]:
    return {"@context": CONTEXT, "@graph": list(graph)}


def _three_packages() -> list[dict[str, Any]]:
    return [
        {"type": "software_Package", "spdxId": "urn:p1", "name": "libfoo", "software_packageVersion": "9.9.9"},
        {"type": "software_Package", "spdxId": "urn:p2", "name": "libbar", "software_packageVersion": "2.0.0"},
        {"type": "software_Package", "spdxId": "urn:p3", "name": "my-app", "software_packageVersion": "1.2.3"},
    ]


class TestApiPrimaryPackage:
    def test_root_element_wins(self) -> None:
        payload = SPDX3Schema.model_validate(
            _doc(
                {"type": "SpdxDocument", "spdxId": "urn:doc", "rootElement": ["urn:p3"]},
                *_three_packages(),
            )
        )

        package, error = _extract_spdx3_primary_package(payload)

        assert error == ""
        assert package is not None
        assert package.name == "my-app"
        assert package.version == "1.2.3"

    def test_compact_single_string_root_element(self) -> None:
        """JSON-LD 1.1 compact form: a one-element set may serialise as a
        bare string."""
        payload = SPDX3Schema.model_validate(
            _doc(
                {"type": "SpdxDocument", "spdxId": "urn:doc", "rootElement": "urn:p2"},
                *_three_packages(),
            )
        )

        package, _ = _extract_spdx3_primary_package(payload)

        assert package is not None
        assert package.name == "libbar"

    def test_describes_kept_when_no_root_element(self) -> None:
        payload = SPDX3Schema.model_validate(
            _doc(
                {"type": "Relationship", "relationshipType": "describes", "from": "urn:doc", "to": ["urn:p2"]},
                *_three_packages(),
            )
        )

        package, _ = _extract_spdx3_primary_package(payload)

        assert package is not None
        assert package.name == "libbar"

    def test_neither_still_falls_back_to_first(self) -> None:
        payload = SPDX3Schema.model_validate(_doc(*_three_packages()))

        package, _ = _extract_spdx3_primary_package(payload)

        assert package is not None
        assert package.name == "libfoo"


class TestBuilderComponentInfo:
    """The deduplicated extraction both release builders now share."""

    def test_root_element_wins(self) -> None:
        info = _spdx3_component_info(
            _doc(
                {"type": "SpdxDocument", "spdxId": "urn:doc", "rootElement": ["urn:p3"]},
                *_three_packages(),
            )
        )

        assert info == ("my-app", "1.2.3", None)

    def test_describes_kept_when_no_root_element(self) -> None:
        info = _spdx3_component_info(
            _doc(
                {"type": "Relationship", "relationshipType": "describes", "from": "urn:doc", "to": ["urn:p2"]},
                *_three_packages(),
            )
        )

        assert info == ("libbar", "2.0.0", None)

    def test_neither_still_falls_back_to_first(self) -> None:
        assert _spdx3_component_info(_doc(*_three_packages())) == ("libfoo", "9.9.9", None)

    def test_legacy_elements_shape(self) -> None:
        """Legacy spdxVersion/elements documents route through the same reader."""
        doc = {
            "spdxVersion": "SPDX-3.0",
            "elements": [
                {"type": "SpdxDocument", "spdxId": "urn:doc", "rootElement": ["urn:p2"]},
                *_three_packages(),
            ],
        }

        assert _spdx3_component_info(doc) == ("libbar", "2.0.0", None)

    def test_no_packages_is_none(self) -> None:
        assert _spdx3_component_info(_doc({"type": "SpdxDocument", "spdxId": "urn:doc"})) is None


class TestCompactDescribesTarget:
    """JSON-LD compact form on the describes fallback: a bare-string ``to``
    must resolve as one id, not be indexed into its first character."""

    def test_api_strategy(self) -> None:
        payload = SPDX3Schema.model_validate(
            _doc(
                {"type": "Relationship", "relationshipType": "describes", "from": "urn:doc", "to": "urn:p2"},
                *_three_packages(),
            )
        )

        package, _ = _extract_spdx3_primary_package(payload)

        assert package is not None
        assert package.name == "libbar"

    def test_builder_helper(self) -> None:
        info = _spdx3_component_info(
            _doc(
                {"type": "Relationship", "relationshipType": "describes", "from": "urn:doc", "to": "urn:p2"},
                *_three_packages(),
            )
        )

        assert info == ("libbar", "2.0.0", None)


def test_a_malformed_graph_falls_back_to_the_elements_alias():
    """The shared iterator's contract, pinned here too: a null @graph must
    not hide a usable elements container from release aggregation."""
    document = {
        "@graph": None,
        "elements": [
            {"type": "software_Package", "spdxId": "urn:p1", "name": "board", "software_packageVersion": "2"},
        ],
    }
    assert _spdx3_component_info(document) == ("board", "2", None)


class TestNonStringDeclaredFields:
    """A package field that is present but not a string.

    ``SPDX3Package`` defaults every field because it is meant to take what it
    is given, but declaring them ``str`` made a present-and-sloppy value fatal
    where an absent one was fine. The exception escaped
    ``SPDX3Schema.packages`` and reached the upload endpoint, which can only
    answer "Invalid request" to a failure from that depth -- so one numeric
    version rejected a document that was otherwise readable.
    """

    @staticmethod
    def _package(**fields: Any) -> SPDX3Package:
        document = {
            "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
            "@graph": [{"type": "software_Package", "spdxId": "urn:p", **fields}],
        }
        return SPDX3Schema.model_validate(document).packages[0]

    def test_a_numeric_version_is_kept_as_written(self) -> None:
        """What the producer meant is a version of "3", not no version."""
        assert self._package(name="p", software_packageVersion=3).version == "3"

    def test_a_numeric_name_is_kept_as_written(self) -> None:
        assert self._package(name=12345, software_packageVersion="1.0").name == "12345"

    def test_an_explicit_null_reads_as_absent(self) -> None:
        """JSON producers write null for an optional field they have nothing
        for; that is the same statement as leaving it out."""
        package = self._package(name=None, software_packageVersion=None)

        assert package.name == ""
        assert package.version == ""

    def test_a_nested_object_falls_back_to_the_default(self) -> None:
        package = self._package(name="p", software_packageVersion={"not": "a string"})

        assert package.version == ""
        assert package.name == "p"

    def test_the_rest_of_the_document_still_parses(self) -> None:
        """The point of the whole thing: one bad field costs that field, not
        the upload."""
        document = {
            "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
            "@graph": [
                {"type": "software_Package", "spdxId": "urn:a", "name": 1, "software_packageVersion": {}},
                {"type": "software_Package", "spdxId": "urn:b", "name": "good", "software_packageVersion": "2.0"},
            ],
        }

        packages = SPDX3Schema.model_validate(document).packages

        assert [(p.name, p.version) for p in packages] == [("1", ""), ("good", "2.0")]

    def test_a_string_field_is_untouched(self) -> None:
        package = self._package(name="p", software_packageVersion="1.0")

        assert (package.name, package.version, package.spdx_id) == ("p", "1.0", "urn:p")


class TestWhereTheLenientParserActuallyApplies:
    """Through ``validate_spdx_sbom``, which is what an upload calls.

    The tests above drive ``SPDX3Schema`` directly, so they establish what the
    parser does but not what an upload does. The two differ: a document
    claiming a 3.0.x ``@context`` is also held to the vendored official
    schema, and that schema rejects a non-string ``software_packageVersion``
    outright. So the lenient parsing cannot rescue such a field on an element
    the schema gate actually inspects -- nor should it, since the document is
    invalid by its own declared spec.

    What it does rescue is the case the gate does not reach:
    ``MAX_VALIDATED_ELEMENTS`` caps the gate at the first 500 graph elements,
    and a real SBOM is much larger than that. In the Yocto fixture here, 224
    of 259 packages sit beyond the cap.
    """

    @staticmethod
    def _yocto() -> dict[str, Any]:
        import json
        from pathlib import Path

        fixture = Path(__file__).parent / "test_data" / "yocto_core-image-minimal.spdx3.json"
        return json.loads(fixture.read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    @staticmethod
    def _package_indexes(graph: list[Any]) -> list[int]:
        return [
            i
            for i, element in enumerate(graph)
            if isinstance(element, dict) and element.get("type") == "software_Package"
        ]

    def test_the_fixture_validates_before_anything_is_broken(self) -> None:
        """A baseline, so the two tests below are about the field and nothing else."""
        from sbomify.apps.sboms.schemas import validate_spdx_sbom

        payload, version = validate_spdx_sbom(self._yocto())

        assert version == "3.0.1"
        assert len(payload.packages) > 200

    def test_a_wrong_typed_version_beyond_the_cap_no_longer_costs_the_upload(self) -> None:
        """The case this change is for, driven through the upload's validator."""
        import copy

        from sbomify.apps.sboms.schemas import validate_spdx_sbom
        from sbomify.apps.sboms.spdx3_validation import MAX_VALIDATED_ELEMENTS

        document = copy.deepcopy(self._yocto())
        graph = document["@graph"]
        beyond = [i for i in self._package_indexes(graph) if i > MAX_VALIDATED_ELEMENTS]
        assert beyond, "fixture no longer has packages beyond the validation cap"

        index = beyond[0]
        # Keyed on spdxId, not name: the fixture has several packages sharing
        # a name (a recipe and its native build, for instance).
        spdx_id = graph[index]["spdxId"]
        graph[index]["software_packageVersion"] = 3

        payload, version = validate_spdx_sbom(document)

        assert version == "3.0.1"
        broken = [package for package in payload.packages if package.spdx_id == spdx_id]
        assert len(broken) == 1
        # Read as the string the producer meant, and every other package is
        # unaffected.
        assert broken[0].version == "3"
        assert len(payload.packages) > 200

    def test_the_schema_gate_still_rejects_one_inside_the_cap(self) -> None:
        """Deliberately pinned, because it bounds the claim.

        An element the official schema inspects is held to it. The lenient
        parser does not -- and must not -- override that: the document is
        invalid by the spec it declares, and saying so is the correct answer.
        """
        import copy

        import pytest

        from sbomify.apps.sboms.schemas import validate_spdx_sbom
        from sbomify.apps.sboms.spdx3_validation import MAX_VALIDATED_ELEMENTS

        document = copy.deepcopy(self._yocto())
        graph = document["@graph"]
        inside = [i for i in self._package_indexes(graph) if i < MAX_VALIDATED_ELEMENTS]
        assert inside, "fixture no longer has packages inside the validation cap"

        graph[inside[0]]["software_packageVersion"] = 3

        with pytest.raises(ValueError, match="schema validation"):
            validate_spdx_sbom(document)
