"""SPDX 3 upload validation stays inside its budget, and stays honest.

#1333 set a 500 ms budget for schema validation on the upload path and shipped
without meeting it: a valid 500-element document cost about 2.3 s. Profiling put
that in reference resolution rather than in the checks, so the schema is now
compiled once and the walk disappears.

Two validators do two jobs. The compiled one answers whether a document is
valid; ``jsonschema`` is asked only to name the violations, and only once the
first has already said no. These tests hold that arrangement to three things:
the same documents pass and fail, a valid one never reaches the slow validator,
and the budget is met.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from sbomify.apps.sboms import spdx3_validation
from sbomify.apps.sboms.spdx3_validation import MAX_VALIDATED_ELEMENTS, spdx3_schema_errors


def _valid(elements: int) -> dict[str, Any]:
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
            "specVersion": "3.0.1",
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
    return {"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": graph}


def _invalid() -> dict[str, Any]:
    document = _valid(2)
    # spdxId must be an IRI, and creationInfo must be present.
    document["@graph"][2] = {"type": "software_Package", "spdxId": 17}
    return document


class TestTheBudget:
    def test_a_full_cap_of_elements_validates_well_inside_the_budget(self) -> None:
        """The number #1333 set, against the case that used to miss it sevenfold.

        The threshold is the budget itself rather than the 84 ms measured, so
        this fails on a real regression and not on a slow CI runner.
        """
        document = _valid(MAX_VALIDATED_ELEMENTS)
        spdx3_schema_errors(document)  # compile once, outside the measurement

        started = time.perf_counter()
        errors = spdx3_schema_errors(document)
        elapsed_ms = (time.perf_counter() - started) * 1000

        assert errors == []
        assert elapsed_ms < 500, f"{elapsed_ms:.0f} ms against a 500 ms budget"


class TestTheSlowValidatorIsOnlyForMessages:
    def test_a_valid_document_never_reaches_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole point of the change.

        Without this, an ImportError or a compile failure would fall through to
        the old path, every other test would still pass, and the 2.3 s would be
        quietly back.
        """

        def _refuse() -> Any:
            raise AssertionError("the enumerator was consulted for a valid document")

        monkeypatch.setattr(spdx3_validation, "_enumerator", _refuse)

        assert spdx3_schema_errors(_valid(20)) == []

    def test_an_invalid_document_does_reach_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """And it is what produces the messages, so it has to be consulted."""
        consulted: list[bool] = []
        real = spdx3_validation._enumerator

        def _spy() -> Any:
            consulted.append(True)
            return real()

        monkeypatch.setattr(spdx3_validation, "_enumerator", _spy)

        errors = spdx3_schema_errors(_invalid())

        assert consulted == [True]
        assert errors


class TestTheVerdictsAreUnchanged:
    def test_a_valid_document_passes(self) -> None:
        assert spdx3_schema_errors(_valid(3)) == []

    def test_an_invalid_document_fails(self) -> None:
        assert spdx3_schema_errors(_invalid())

    def test_the_messages_still_read_as_pointers(self) -> None:
        """``schemas.py`` puts these straight into an API error response."""
        errors = spdx3_schema_errors(_invalid())

        assert all(": " in error for error in errors)
        assert all(error.startswith("/") or error.startswith("(document root)") for error in errors)

    @pytest.mark.parametrize("limit", [1, 3, 5])
    def test_the_limit_still_bounds_the_list(self, limit: int) -> None:
        errors = spdx3_schema_errors(_invalid(), limit=limit)

        assert len(errors) <= limit


class TestTheCapIsUnchanged:
    def test_the_ceiling_did_not_move_with_the_validator(self) -> None:
        """Lifting it changes which documents are accepted, which is a separate
        decision from making the check cheaper. Pinned so a later performance
        change does not quietly widen what gets rejected."""
        assert MAX_VALIDATED_ELEMENTS == 500

    def test_a_graph_past_the_cap_is_still_checked_on_a_prefix(self) -> None:
        document = _valid(MAX_VALIDATED_ELEMENTS + 50)

        assert spdx3_schema_errors(document) == []
