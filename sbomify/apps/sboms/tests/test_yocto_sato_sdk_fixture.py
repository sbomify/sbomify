"""The large Yocto fixture, checked against what the README says about it.

Committing a 4.2 MiB gzip that nothing loads means CI never notices a truncated
upload or a change in how the graph reads. The parsed document is read once for
the whole module and asserted against the counts the README documents, so the
two cannot drift apart and a broken archive fails here rather than in whatever
uses it next.

The provenance test is the one deliberate second pass. It hashes the
decompressed bytes, which the parsed document cannot answer for: a re-wrapped
archive or a reordered key gives an identical graph and a different digest. It
streams in 1 MiB chunks and never holds the 50 MiB, and the whole module still
runs in well under a second.

Deliberately no schema validation: that is what makes it cheap enough to keep in
the per-commit suite.
"""

import collections
import gzip
import hashlib
import json
import pathlib

import pytest

FIXTURE = pathlib.Path(__file__).parent.resolve() / "test_data" / "yocto_core-image-sato-sdk.spdx3.json.gz"

# What Yocto published, recorded in the test_data README beside the download
# instructions. The gzip wrapper is ours; the bytes inside it are theirs.
DOCUMENTED_SHA256 = "ad7c716ee239032369ebc07d4eb5ef9eb1d87394dd6ff43a99298cf1a50fd481"


@pytest.fixture(scope="module")
def document() -> dict:
    """Gunzipped once for the whole module; it is the point of the fixture."""
    with gzip.open(FIXTURE) as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def graph(document: dict) -> list:
    return document["@graph"]


@pytest.fixture(scope="module")
def counts(graph: list) -> collections.Counter:
    return collections.Counter(e.get("type") for e in graph if isinstance(e, dict))


def test_the_document_is_the_one_yocto_published():
    """The README's provenance claim, checked instead of asserted in prose.

    Every other test here reads the parsed graph, so a re-wrapped archive or an
    edited field that left the counts alone would pass the lot. Hashing the
    decompressed bytes is what lets CI fail on the claim the README makes.
    """
    digest = hashlib.sha256()
    with gzip.open(FIXTURE) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    assert digest.hexdigest() == DOCUMENTED_SHA256


def test_the_archive_opens_and_is_spdx3(document: dict):
    """A truncated archive fails here first."""
    from sbomify.apps.plugins.builtins._spdx3_helpers import is_spdx3

    assert is_spdx3(document)
    assert "3.0.1" in str(document["@context"])


def test_the_graph_is_the_documented_size(graph: list):
    assert len(graph) == 68511


def test_the_element_table_is_the_whole_inventory(counts: collections.Counter, graph: list):
    """The README table is a complete breakdown, not a selection of highlights."""
    documented = {
        "software_File": 50828,
        "Relationship": 6324,
        "LifecycleScopedRelationship": 5847,
        "software_Package": 3813,
        "build_Build": 566,
        "CreationInfo": 383,
        "security_Vulnerability": 291,
        "security_VexFixedVulnAssessmentRelationship": 205,
        "simplelicensing_LicenseExpression": 149,
        "security_VexNotAffectedVulnAssessmentRelationship": 86,
        "simplelicensing_SimpleLicensingText": 15,
        "SpdxDocument": 1,
        "software_Sbom": 1,
        "Organization": 1,
        "Tool": 1,
    }

    assert dict(counts) == documented
    assert sum(documented.values()) == len(graph)


def test_the_vex_statements_are_the_documented_shape(graph: list):
    not_affected = [e for e in graph if e.get("type") == "security_VexNotAffectedVulnAssessmentRelationship"]
    with_justification = [e for e in not_affected if e.get("security_justificationType")]

    assert len(not_affected) == 86
    assert len(with_justification) == 37


def test_the_packages_split_by_purpose_as_documented(graph: list):
    packages = [e for e in graph if e.get("type") == "software_Package"]
    purposes = collections.Counter(e.get("software_primaryPurpose") for e in packages)

    assert purposes["source"] == 1649
    assert purposes["install"] == 1600
    assert purposes["specification"] == 563
    assert purposes["archive"] == 1


@pytest.fixture(scope="module")
def vex_statements(document: dict) -> list:
    """What the VEX reader makes of the graph, derived once."""
    from sbomify.apps.vulnerability_scanning.vex_formats import derive_spdx3_vex_suppressions

    return derive_spdx3_vex_suppressions(document)


def test_the_vex_reader_returns_the_documented_statements(vex_statements: list):
    """Counting element types in the raw JSON does not exercise the reader.

    A regression in how it walks a 68k-element graph would leave every other
    test here green while the document silently yielded nothing.
    """
    assert len(vex_statements) == 291


def test_the_statements_keep_their_state_split(vex_statements: list):
    states = collections.Counter(statement.get("state") for statement in vex_statements)

    assert states["resolved"] == 205
    assert states["not_affected"] == 86


def test_no_statement_widens_to_the_whole_document(vex_statements: list):
    """Product scoping fails closed here: every statement names its packages.

    A statement that resolved to no package would be skipped rather than
    suppressing by vulnerability id alone, so a non-zero count here would mean
    the reader had started widening.
    """
    assert [s for s in vex_statements if s.get("product_scoped")] == []
