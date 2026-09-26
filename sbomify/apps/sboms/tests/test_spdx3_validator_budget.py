"""SPDX 3 upload validation stays inside its budget, and stays honest.

#1333 set a 500 ms budget for schema validation on the upload path and shipped
without meeting it: a valid 500-element document cost about 2.3 s. Profiling put
that in reference resolution rather than in the checks, so the schema is now
compiled once and the walk disappears.

Two validators do two jobs. The compiled one answers whether a document is
valid; ``jsonschema`` is asked only to name the violations, and only once the
first has already said no. These tests hold that arrangement to three things,
under each vendored schema: the same documents pass and fail, a valid one never
reaches the slow validator, and the budget is met.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from sbomify.apps.plugins.tests import spdx3_corpus as corpus
from sbomify.apps.sboms import spdx3_validation
from sbomify.apps.sboms.spdx3_validation import MAX_VALIDATED_ELEMENTS, spdx3_schema_errors

TEST_DATA = Path(__file__).resolve().parent / "test_data"
YOCTO_OUTPUT = {
    "3.0.0": TEST_DATA / "yocto_core-image-minimal.spdx3.0.0.json",
    "3.0.1": TEST_DATA / "yocto_core-image-minimal.spdx3.json",
}
VERSIONS = sorted(spdx3_validation.SCHEMA_PATHS)


def _valid(elements: int, version: str = "3.0.1") -> dict[str, Any]:
    graph: list[dict[str, Any]] = [
        {
            "type": "SpdxDocument",
            "spdxId": "https://example.test/doc",
            "creationInfo": "_:ci",
            "profileConformance": ["core", "software"],
            "rootElement": ["https://example.test/pkg-0"],
        },
        {
            "type": "CreationInfo",
            "@id": "_:ci",
            "specVersion": version,
            "created": "2026-09-21T07:00:00Z",
            "createdBy": ["https://example.test/tool"],
        },
    ]
    for index in range(elements):
        graph.append(
            {
                "type": "software_Package",
                "spdxId": f"https://example.test/pkg-{index}",
                "creationInfo": "_:ci",
                "name": f"pkg-{index}",
                "software_packageVersion": "1.0",
            }
        )
    return {"@context": f"https://spdx.org/rdf/{version}/spdx-context.jsonld", "@graph": graph}


def _invalid(version: str = "3.0.1") -> dict[str, Any]:
    document = _valid(2, version)
    # spdxId must be an IRI, and creationInfo must be present.
    document["@graph"][2] = {"type": "software_Package", "spdxId": 17}
    return document


@pytest.mark.parametrize("version", VERSIONS)
class TestTheBudget:
    def test_a_full_cap_of_elements_validates_well_inside_the_budget(self, version: str) -> None:
        """The number #1333 set, against the case that used to miss it sevenfold.

        The threshold is the budget itself rather than the 84 ms measured, so
        this fails on a real regression and not on a slow CI runner.
        """
        document = _valid(MAX_VALIDATED_ELEMENTS, version)
        spdx3_schema_errors(document, version)  # compile once, outside the measurement

        started = time.perf_counter()
        errors = spdx3_schema_errors(document, version)
        elapsed_ms = (time.perf_counter() - started) * 1000

        assert errors == []
        assert elapsed_ms < 500, f"{elapsed_ms:.0f} ms against a 500 ms budget"


@pytest.mark.parametrize("version", VERSIONS)
class TestTheSlowValidatorIsOnlyForMessages:
    def test_a_valid_document_never_reaches_it(self, version: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole point of the change.

        Without this, an ImportError or a compile failure would fall through to
        the old path, every other test would still pass, and the 2.3 s would be
        quietly back.
        """

        def _refuse(*_: Any) -> Any:
            raise AssertionError("the enumerator was consulted for a valid document")

        monkeypatch.setattr(spdx3_validation, "_enumerator", _refuse)

        assert spdx3_schema_errors(_valid(20, version), version) == []

    def test_an_invalid_document_does_reach_it(self, version: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """And it is what produces the messages, so it has to be consulted."""
        consulted: list[bool] = []
        real = spdx3_validation._enumerator

        def _spy(schema_version: str) -> Any:
            consulted.append(True)
            return real(schema_version)

        monkeypatch.setattr(spdx3_validation, "_enumerator", _spy)

        errors = spdx3_schema_errors(_invalid(version), version)

        assert consulted == [True]
        assert errors


@pytest.mark.parametrize("version", VERSIONS)
class TestTheVerdictsAreUnchanged:
    def test_a_valid_document_passes(self, version: str) -> None:
        assert spdx3_schema_errors(_valid(3, version), version) == []

    def test_an_invalid_document_fails(self, version: str) -> None:
        assert spdx3_schema_errors(_invalid(version), version)

    def test_the_messages_still_read_as_pointers(self, version: str) -> None:
        """``schemas.py`` puts these straight into an API error response."""
        errors = spdx3_schema_errors(_invalid(version), version)

        assert all(": " in error for error in errors)
        assert all(error.startswith("/") or error.startswith("(document root)") for error in errors)

    def test_the_messages_point_at_the_element_not_the_document(self, version: str) -> None:
        """The 3.0.0 root is a oneOf, so over the whole document a bad element
        reads as the root failing, with the document itself as the message."""
        errors = spdx3_schema_errors(_invalid(version), version)

        assert errors
        assert all(error.startswith("/@graph/2") for error in errors)

    @pytest.mark.parametrize("limit", [1, 3, 5])
    def test_the_limit_still_bounds_the_list(self, version: str, limit: int) -> None:
        errors = spdx3_schema_errors(_invalid(version), version, limit=limit)

        assert len(errors) <= limit


class TestTheGateClosesWhatTheSchemaCloses:
    """The schema closes every element and every inline object with
    ``unevaluatedProperties: false``, and fastjsonschema does not implement that
    keyword. So a property the schema refuses passed the gate, the enumerator was
    never asked, and the document was accepted. jsonschema refuses each rejection
    case here, and each one passed the gate until it checked keys itself.
    """

    @pytest.mark.parametrize("version", VERSIONS)
    def test_a_made_up_property_is_rejected(self, version: str) -> None:
        document = _valid(3, version)
        document["@graph"][2]["totally_made_up"] = 1

        errors = spdx3_schema_errors(document, version)

        assert errors
        assert "totally_made_up" in errors[0]

    @pytest.mark.parametrize("version", VERSIONS)
    def test_a_made_up_root_property_is_rejected(self, version: str) -> None:
        document = _valid(3, version)
        document["junk"] = 1

        assert spdx3_schema_errors(document, version)

    @pytest.mark.parametrize("version", VERSIONS)
    def test_a_property_another_class_declares_is_rejected(self, version: str) -> None:
        """Checked per class: ``specVersion`` is an SPDX property, but a
        CreationInfo's, not a package's."""
        document = _valid(3, version)
        document["@graph"][2]["specVersion"] = version

        errors = spdx3_schema_errors(document, version)

        assert errors
        assert "specVersion" in errors[0]

    @pytest.mark.parametrize("version", VERSIONS)
    def test_a_made_up_property_on_an_inline_object_is_rejected(self, version: str) -> None:
        document = _valid(3, version)
        document["@graph"][2]["verifiedUsing"] = [
            {"type": "Hash", "algorithm": "sha256", "hashValue": "a" * 64, "totally_made_up": 1}
        ]

        assert spdx3_schema_errors(document, version)

    @pytest.mark.parametrize(
        ("builder", "version"),
        [(builder, "3.0.1") for builder in corpus.SCHEMA_VALID_BUILDERS]
        + [(corpus.spdx_3_0_0, "3.0.0"), (corpus.syft_shaped, "3.0.0")],
        ids=lambda value: getattr(value, "__name__", value),
    )
    def test_a_made_up_property_is_rejected_on_every_element(
        self, builder: Callable[[], dict[str, Any]], version: str
    ) -> None:
        """Every class the corpus uses, one element at a time."""
        document = builder()
        for index, element in enumerate(document["@graph"]):
            mutated = copy.deepcopy(document)
            mutated["@graph"][index]["totally_made_up"] = 1

            assert spdx3_schema_errors(mutated, version), (
                f"@graph/{index} ({element['type']}) accepted a made-up property"
            )

    @pytest.mark.parametrize("version", VERSIONS)
    def test_an_open_extension_carries_what_it_likes(self, version: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """The schema leaves an extension object open, and Yocto 6.0 writes
        them. Its keys are not the gate's to refuse, and a document carrying one
        must not pay the slow walk either."""

        def _refuse(*_: Any) -> Any:
            raise AssertionError("the enumerator was consulted for a valid document")

        monkeypatch.setattr(spdx3_validation, "_enumerator", _refuse)
        document = _valid(3, version)
        document["@graph"][2]["extension"] = [
            {"type": "https://example.test/ns/Note", "https://example.test/ns/text": "built on a Tuesday"}
        ]

        assert spdx3_schema_errors(document, version) == []

    @pytest.mark.parametrize(
        ("builder", "version"),
        [(builder, "3.0.1") for builder in corpus.SCHEMA_VALID_BUILDERS]
        + [(corpus.spdx_3_0_0, "3.0.0"), (corpus.syft_shaped, "3.0.0")],
        ids=lambda value: getattr(value, "__name__", value),
    )
    def test_a_conformant_document_still_never_reaches_the_enumerator(
        self, builder: Callable[[], dict[str, Any]], version: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The key check must vouch for every property a conformant document
        uses, or the 2.3 s walk comes back for valid documents."""

        def _refuse(*_: Any) -> Any:
            raise AssertionError("the enumerator was consulted for a valid document")

        monkeypatch.setattr(spdx3_validation, "_enumerator", _refuse)

        assert spdx3_schema_errors(builder(), version) == []

    @pytest.mark.parametrize("version", VERSIONS)
    def test_real_yocto_output_never_reaches_the_enumerator(
        self, version: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same on a published Yocto document, whose elements carry far more
        of the schema than the corpus does."""

        def _refuse(*_: Any) -> Any:
            raise AssertionError("the enumerator was consulted for a valid document")

        monkeypatch.setattr(spdx3_validation, "_enumerator", _refuse)

        assert spdx3_schema_errors(json.loads(YOCTO_OUTPUT[version].read_text()), version) == []


@pytest.mark.parametrize("version", VERSIONS)
class TestOnlyARefusedElementReachesJsonschema:
    """jsonschema costs up to 290 ms an element under 3.0.0. Walked in order, a
    graph whose one bad element sits near the cap would hold the upload for over
    a minute before the first message."""

    def test_the_other_elements_never_reach_it(self, version: str, monkeypatch: pytest.MonkeyPatch) -> None:
        real = spdx3_validation._element_enumerator
        asked: list[Any] = []

        class _Spy:
            def __init__(self, inner: Any) -> None:
                self.inner = inner

            def iter_errors(self, element: dict[str, Any]) -> Any:
                asked.append(element.get("spdxId"))
                return self.inner.iter_errors(element)

        monkeypatch.setattr(spdx3_validation, "_element_enumerator", lambda schema_version: _Spy(real(schema_version)))
        document = _valid(300, version)
        document["@graph"][250] = {"type": "software_Package", "spdxId": 17}

        errors = spdx3_schema_errors(document, version)

        assert errors
        assert all(error.startswith("/@graph/250") for error in errors)
        assert asked == [17]

    def test_a_bad_root_does_not_send_every_element(self, version: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each element is gated alone under the ``@context`` the schema pins,
        not the document's, or one wrong root would condemn them all."""

        def _refuse(*_: Any) -> Any:
            raise AssertionError("an element was sent to jsonschema for a fault at the root")

        monkeypatch.setattr(spdx3_validation, "_element_enumerator", _refuse)
        document = _valid(300, version)
        document["@context"] = "https://spdx.org/rdf/3.0.9/spdx-context.jsonld"

        errors = spdx3_schema_errors(document, version)

        assert errors == [f"/@context: 'https://spdx.org/rdf/{version}/spdx-context.jsonld' was expected"]


def _closed_objects(node: Any) -> Iterator[dict[str, Any]]:
    """Every schema node that closes an object with ``unevaluatedProperties: false``."""
    if isinstance(node, dict):
        if node.get("unevaluatedProperties") is False:
            yield node
        for value in node.values():
            yield from _closed_objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _closed_objects(value)


@pytest.mark.parametrize("version", VERSIONS)
class TestTheSchemaIsShapedTheWayTheKeyCheckReadsIt:
    """The key check leans on two facts about each vendored schema. They are
    pinned here, so a schema that breaks either fails a test rather than
    quietly widening what the gate accepts."""

    @pytest.fixture
    def schema(self, version: str) -> dict[str, Any]:
        schema: dict[str, Any] = json.loads(spdx3_validation.SCHEMA_PATHS[version].read_text())
        return schema

    def test_every_closed_object_below_the_root_is_a_derived_class(self, schema: dict[str, Any]) -> None:
        """So an object the gate passed at a closed site is an instance of a
        class whose properties the derivation knows."""
        defs = schema["$defs"]
        declared = spdx3_validation._declared_properties_of(schema)
        sites = [site for site in _closed_objects(schema) if site is not schema]

        assert sites
        for site in sites:
            assert site.keys() <= {"type", "$ref", "anyOf", "unevaluatedProperties"}
            refs = [site["$ref"]] if "$ref" in site else [member["$ref"] for member in site["anyOf"]]
            names = [ref.removeprefix("#/$defs/") for ref in refs]
            if names == ["AnyClass"]:
                names = [member["$ref"].removeprefix("#/$defs/") for member in defs["AnyClass"]["anyOf"]]
            assert all(name in declared for name in names), names

    def test_every_closed_class_takes_its_own_name_as_its_type_and_nothing_else(self, schema: dict[str, Any]) -> None:
        """So an object whose type names no closed class never passed the gate
        through one, and leaving its own keys unchecked cannot miss anything."""
        defs = schema["$defs"]
        declared = spdx3_validation._declared_properties_of(schema)

        for name, properties in declared.items():
            if properties is None:
                continue
            if "if" in defs[name]:  # 3.0.1
                assert defs[name]["if"] == {
                    "type": "object",
                    "properties": {"type": {"const": name}},
                    "required": ["type"],
                }
            else:  # 3.0.0 names the class in the first part of its allOf
                assert defs[name]["allOf"][0]["properties"]["type"] == {"oneOf": [{"const": name}]}


class TestTheKeyCheckFailsClosed:
    def test_a_conditional_property_is_refused_rather_than_guessed(self) -> None:
        """Collecting properties through an ``anyOf`` would credit a class with
        properties only some of its instances may carry, and an overcount here
        is a document the gate waves through. So the derivation refuses."""
        schema = {
            "$defs": {
                "AnyClass": {"anyOf": [{"$ref": "#/$defs/Thing"}]},
                "Thing": {"allOf": [{"anyOf": [{"properties": {"a": {}}}, {"properties": {"b": {}}}]}]},
            }
        }

        with pytest.raises(ValueError, match="anyOf"):
            spdx3_validation._declared_properties_of(schema)

    def test_a_schema_it_cannot_read_is_loud_not_a_rejection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resolved before the gate runs, like the gate itself: a derivation
        that raises must not read as "this document is invalid"."""

        def _unreadable(*_: Any) -> Any:
            raise ValueError("cannot derive")

        monkeypatch.setattr(spdx3_validation, "_declared_properties", _unreadable)

        with pytest.raises(ValueError, match="cannot derive"):
            spdx3_schema_errors(_valid(3), "3.0.1")


class TestTheCapIsUnchanged:
    def test_the_ceiling_did_not_move_with_the_validator(self) -> None:
        """Lifting it changes which documents are accepted, which is a separate
        decision from making the check cheaper. Pinned so a later performance
        change does not quietly widen what gets rejected."""
        assert MAX_VALIDATED_ELEMENTS == 500

    def test_a_graph_past_the_cap_is_still_checked_on_a_prefix(self) -> None:
        document = _valid(MAX_VALIDATED_ELEMENTS + 50)

        assert spdx3_schema_errors(document, "3.0.1") == []
