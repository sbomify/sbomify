"""The corpus guard: conformant documents validate, score, and never lose to
legacy spellings.

Two properties, each of which failed silently before:

1. Every fixture marked conformant validates against the vendored official
   ``spdx_3.0.1-schema.json`` — so a fixture that drifts from the spec fails
   here rather than quietly training the plugins on the wrong shape.
2. A conformant document scores at least as well as the same data written
   with the legacy spellings, across all four compliance plugins. Reverting
   any of the spec-field fixes flips this red.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin
from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin
from sbomify.apps.plugins.builtins.fda_medical_device_cybersecurity import FDAMedicalDevicePlugin
from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin
from sbomify.apps.plugins.tests import spdx3_corpus as corpus

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sboms" / "schemas" / "spdx_3.0.1-schema.json"

PLUGINS = [NTIAMinimumElementsPlugin, CISAMinimumElementsPlugin, FDAMedicalDevicePlugin, BSICompliancePlugin]


@cache
def _validator() -> Any:
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA_PATH.read_text())
    return Draft202012Validator(schema)


def _schema_errors(document: dict[str, Any]) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message[:120]}" for e in _validator().iter_errors(document)
    ]


class TestCorpusValidatesAgainstTheOfficialSchema:
    @pytest.mark.parametrize("builder", corpus.SCHEMA_VALID_BUILDERS, ids=lambda b: b.__name__)
    def test_fixture_is_schema_valid(self, builder) -> None:
        errors = _schema_errors(builder())

        assert errors == []

    def test_legacy_counterpart_is_deliberately_invalid(self) -> None:
        """The plural spelling is invalid under unevaluatedProperties: false —
        which is the whole point: the schema itself refuses the shape the
        plugins used to require."""
        assert _schema_errors(corpus.legacy_spelling_counterpart()) != []


def _scores(document: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """{plugin: (pass_count, fail_count)} over the four compliance plugins."""
    results: dict[str, tuple[int, int]] = {}
    for plugin_cls in PLUGINS:
        findings = plugin_cls()._validate_spdx3(document)
        statuses = [f.status for f in findings]
        results[plugin_cls.__name__] = (statuses.count("pass"), statuses.count("fail"))
    return results


class TestConformantNeverScoresWorse:
    def test_spec_spelling_beats_or_ties_legacy_everywhere(self) -> None:
        conformant = _scores(corpus.purl_via_external_identifier_only())
        legacy = _scores(corpus.legacy_spelling_counterpart())

        for plugin_name, (spec_pass, spec_fail) in conformant.items():
            legacy_pass, legacy_fail = legacy[plugin_name]
            assert spec_pass >= legacy_pass, f"{plugin_name}: conformant passes {spec_pass} < legacy {legacy_pass}"
            assert spec_fail <= legacy_fail, f"{plugin_name}: conformant fails {spec_fail} > legacy {legacy_fail}"

    def test_first_class_purl_property_scores_like_an_identifier(self) -> None:
        via_property = _scores(corpus.purl_via_software_package_url_only())
        via_identifier = _scores(corpus.purl_via_external_identifier_only())

        assert via_property == via_identifier

    @pytest.mark.parametrize(
        "builder",
        [corpus.inline_agents, corpus.software_agent_supplier, corpus.yocto_shaped, corpus.syft_shaped],
        ids=lambda b: b.__name__,
    )
    def test_every_producer_shape_completes_without_an_exception(self, builder) -> None:
        """The inline-Agent shape used to TypeError two plugins into a FAILED
        run; a corpus document must never take a plugin down."""
        for plugin_name, (pass_count, fail_count) in _scores(builder()).items():
            assert pass_count + fail_count > 0, f"{plugin_name} produced no gradeable findings"

    def test_inline_and_referenced_suppliers_score_identically(self) -> None:
        """Swapping the supplier's shape (reference vs inline) and type
        (Organization vs SoftwareAgent) must not move the score."""
        referenced = _scores(corpus.software_agent_supplier())
        inline = _scores(corpus.inline_agents())

        assert referenced == inline
