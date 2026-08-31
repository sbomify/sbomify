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
from sbomify.apps.sboms.schemas import SPDX3Schema

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
