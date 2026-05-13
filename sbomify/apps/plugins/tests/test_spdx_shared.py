"""Direct unit tests for sbomify.apps.plugins.builtins._spdx_shared helpers.

The BSI / CISA / FDA compliance plugins all consume this module — a
regression in the shared logic propagates to every plugin, so the
contract is worth pinning down with focused unit tests rather than
relying solely on end-to-end plugin assessments.

Organised by helper, each with:
- happy path (canonical spec-compliant input),
- complex cases (multiple SpdxDocuments, mixed subjects, etc.),
- bad input (non-dict, non-list, non-string types),
- backward compat (legacy field names and JSON-LD compact form).
"""

from __future__ import annotations

from typing import Any

import pytest

from sbomify.apps.plugins.builtins._spdx_shared import (
    iter_spdx3_elements,
    spdx2_annotation_targets_document,
    spdx2_root_spdxid,
    spdx3_annotation_subject_matches,
    spdx3_document_subjects,
)

# ============================================================================
# spdx2_root_spdxid
# ============================================================================


class TestSpdx2RootSpdxid:
    """SPDX 2.x: identifies the BOM root via documentDescribes or a DESCRIBES
    relationship (per SPDX 2.3 §11)."""

    def test_documentDescribes_wins(self) -> None:
        data = {"documentDescribes": ["SPDXRef-Package-Primary"]}
        assert spdx2_root_spdxid(data) == "SPDXRef-Package-Primary"

    def test_describes_relationship_fallback(self) -> None:
        data = {
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-Root",
                }
            ]
        }
        assert spdx2_root_spdxid(data) == "SPDXRef-Package-Root"

    def test_describes_case_insensitive_on_type(self) -> None:
        """relationshipType is matched case-insensitively so upstream
        tools that serialise `describes` (lowercase) still work."""
        data = {
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "describes",
                    "relatedSpdxElement": "SPDXRef-Package-X",
                }
            ]
        }
        assert spdx2_root_spdxid(data) == "SPDXRef-Package-X"

    def test_no_root_returns_none(self) -> None:
        assert spdx2_root_spdxid({}) is None

    def test_empty_documentDescribes_falls_back_to_relationships(self) -> None:
        data = {
            "documentDescribes": [],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Pkg",
                }
            ],
        }
        assert spdx2_root_spdxid(data) == "SPDXRef-Pkg"

    def test_non_string_documentDescribes_entry_ignored(self) -> None:
        data = {"documentDescribes": [None, {"oops": "not-a-ref"}, 42]}
        assert spdx2_root_spdxid(data) is None

    @pytest.mark.parametrize(
        "relationships",
        ["not-a-list", {"dict": "not-list"}, None, 42],
    )
    def test_malformed_relationships_do_not_raise(self, relationships: Any) -> None:
        data: dict[str, Any] = {"relationships": relationships}
        # Should return None, not raise.
        assert spdx2_root_spdxid(data) is None

    def test_relationship_with_non_dict_entry_skipped(self) -> None:
        data = {
            "relationships": [
                "not-a-dict",
                None,
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Pkg",
                },
            ]
        }
        assert spdx2_root_spdxid(data) == "SPDXRef-Pkg"

    def test_non_describes_relationships_ignored(self) -> None:
        data = {
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Pkg",
                }
            ]
        }
        assert spdx2_root_spdxid(data) is None


# ============================================================================
# spdx2_annotation_targets_document
# ============================================================================


class TestSpdx2AnnotationTargetsDocument:
    """SPDX 2.3 §12: an annotation with spdxElementId pointing at a specific
    package describes that package, not the document."""

    def test_explicit_SPDXRef_DOCUMENT(self) -> None:
        ann = {"spdxElementId": "SPDXRef-DOCUMENT"}
        assert spdx2_annotation_targets_document(ann, None) is True

    def test_explicit_match_to_root(self) -> None:
        ann = {"spdxElementId": "SPDXRef-Pkg-Root"}
        assert spdx2_annotation_targets_document(ann, "SPDXRef-Pkg-Root") is True

    def test_explicit_match_to_non_root_rejected(self) -> None:
        ann = {"spdxElementId": "SPDXRef-Pkg-Dep"}
        assert spdx2_annotation_targets_document(ann, "SPDXRef-Pkg-Root") is False

    def test_empty_subject_with_root_accepted(self) -> None:
        """Real SPDX tools often omit spdxElementId on doc-level annotations."""
        ann = {"spdxElementId": ""}
        assert spdx2_annotation_targets_document(ann, "SPDXRef-Pkg-Root") is True

    def test_empty_subject_without_root_rejected(self) -> None:
        """Without a DESCRIBES target the annotation is unanchored."""
        ann = {"spdxElementId": ""}
        assert spdx2_annotation_targets_document(ann, None) is False

    def test_missing_subject_treated_as_empty(self) -> None:
        ann: dict[str, Any] = {}
        assert spdx2_annotation_targets_document(ann, "SPDXRef-Root") is True
        assert spdx2_annotation_targets_document(ann, None) is False

    def test_non_string_subject_rejected(self) -> None:
        for bad in [None, 42, ["ref"], {"dict": "nope"}]:
            ann = {"spdxElementId": bad}
            assert spdx2_annotation_targets_document(ann, "SPDXRef-Root") is False


# ============================================================================
# spdx3_document_subjects
# ============================================================================


class TestSpdx3DocumentSubjects:
    """SPDX 3.0.1 Core.SpdxDocument: document_ids = SpdxDocument spdxIds;
    root_element_ids = declared BOM subjects. The two sets are disjoint
    by design (rootElement must not be of type SpdxDocument)."""

    def test_canonical_graph(self) -> None:
        data = {
            "@graph": [
                {
                    "type": "SpdxDocument",
                    "spdxId": "SPDXRef-Document",
                    "rootElement": ["SPDXRef-Pkg-1"],
                }
            ]
        }
        doc_ids, root_ids = spdx3_document_subjects(data)
        assert doc_ids == {"SPDXRef-Document"}
        assert root_ids == {"SPDXRef-Pkg-1"}

    def test_legacy_elements_alias(self) -> None:
        """Some emitters use `elements` instead of `@graph`."""
        data = {
            "elements": [
                {
                    "type": "SpdxDocument",
                    "spdxId": "SPDXRef-Document",
                    "rootElement": ["SPDXRef-Pkg"],
                }
            ]
        }
        doc_ids, root_ids = spdx3_document_subjects(data)
        assert doc_ids == {"SPDXRef-Document"}
        assert root_ids == {"SPDXRef-Pkg"}

    def test_at_id_fallback_for_spdxId(self) -> None:
        """JSON-LD compact form uses @id — accepted as a fallback."""
        data = {"@graph": [{"@type": "SpdxDocument", "@id": "SPDXRef-Document"}]}
        doc_ids, _ = spdx3_document_subjects(data)
        assert doc_ids == {"SPDXRef-Document"}

    def test_rootElement_as_bare_string_normalised(self) -> None:
        """JSON-LD 1.1 compact form: a single-value property may be a bare
        string rather than a single-item array."""
        data = {
            "@graph": [
                {
                    "type": "SpdxDocument",
                    "spdxId": "SPDXRef-Document",
                    "rootElement": "SPDXRef-Pkg-1",
                }
            ]
        }
        _, root_ids = spdx3_document_subjects(data)
        assert root_ids == {"SPDXRef-Pkg-1"}

    def test_multiple_SpdxDocument_entries_merged(self) -> None:
        """If a graph contains multiple SpdxDocuments, all their ids /
        rootElements are collected."""
        data = {
            "@graph": [
                {
                    "type": "SpdxDocument",
                    "spdxId": "SPDXRef-Document-A",
                    "rootElement": ["SPDXRef-Pkg-A"],
                },
                {
                    "type": "SpdxDocument",
                    "spdxId": "SPDXRef-Document-B",
                    "rootElement": ["SPDXRef-Pkg-B"],
                },
            ]
        }
        doc_ids, root_ids = spdx3_document_subjects(data)
        assert doc_ids == {"SPDXRef-Document-A", "SPDXRef-Document-B"}
        assert root_ids == {"SPDXRef-Pkg-A", "SPDXRef-Pkg-B"}

    def test_no_SpdxDocument_returns_empty_sets(self) -> None:
        data = {"@graph": [{"type": "software_Package", "spdxId": "SPDXRef-Pkg"}]}
        doc_ids, root_ids = spdx3_document_subjects(data)
        assert doc_ids == set()
        assert root_ids == set()

    def test_SpdxDocument_without_rootElement_still_yields_doc_id(self) -> None:
        data = {"@graph": [{"type": "SpdxDocument", "spdxId": "SPDXRef-Document"}]}
        doc_ids, root_ids = spdx3_document_subjects(data)
        assert doc_ids == {"SPDXRef-Document"}
        assert root_ids == set()

    @pytest.mark.parametrize("graph_val", ["a-string", 42, None, True])
    def test_non_list_graph_returns_empty(self, graph_val: Any) -> None:
        """Malformed @graph (non-list, non-dict) must not crash."""
        assert spdx3_document_subjects({"@graph": graph_val}) == (set(), set())

    def test_non_dict_entry_skipped(self) -> None:
        data = {
            "@graph": [
                "not-a-dict",
                None,
                {"type": "SpdxDocument", "spdxId": "SPDXRef-Document"},
            ]
        }
        doc_ids, _ = spdx3_document_subjects(data)
        assert doc_ids == {"SPDXRef-Document"}

    def test_non_list_rootElement_skipped_without_crash(self) -> None:
        data = {
            "@graph": [
                {
                    "type": "SpdxDocument",
                    "spdxId": "SPDXRef-Document",
                    "rootElement": 42,  # hostile
                }
            ]
        }
        doc_ids, root_ids = spdx3_document_subjects(data)
        assert doc_ids == {"SPDXRef-Document"}
        assert root_ids == set()

    def test_non_string_rootElement_entry_skipped(self) -> None:
        data = {
            "@graph": [
                {
                    "type": "SpdxDocument",
                    "spdxId": "SPDXRef-Document",
                    "rootElement": [None, 42, {"nested": "dict"}, "", "SPDXRef-Valid"],
                }
            ]
        }
        _, root_ids = spdx3_document_subjects(data)
        assert root_ids == {"SPDXRef-Valid"}

    def test_single_node_graph_accepted(self) -> None:
        """JSON-LD allows @graph to be a single node object, not just a list."""
        data = {"@graph": {"type": "SpdxDocument", "spdxId": "SPDXRef-Document"}}
        doc_ids, _ = spdx3_document_subjects(data)
        assert doc_ids == {"SPDXRef-Document"}


# ============================================================================
# spdx3_annotation_subject_matches
# ============================================================================


class TestSpdx3AnnotationSubjectMatches:
    """Accepts an annotation as document-scoped iff its subject is in
    document_ids OR root_element_ids, with a special gate for empty
    subject: require root_element_ids to be non-empty."""

    @pytest.fixture
    def doc_ids(self) -> set[str]:
        return {"SPDXRef-Document"}

    @pytest.fixture
    def root_ids(self) -> set[str]:
        return {"SPDXRef-Pkg-Root"}

    def test_subject_matches_document_id(self, doc_ids: set[str], root_ids: set[str]) -> None:
        ann = {"subject": "SPDXRef-Document"}
        assert spdx3_annotation_subject_matches(ann, doc_ids, root_ids) is True

    def test_subject_matches_rootElement(self, doc_ids: set[str], root_ids: set[str]) -> None:
        ann = {"subject": "SPDXRef-Pkg-Root"}
        assert spdx3_annotation_subject_matches(ann, doc_ids, root_ids) is True

    def test_subject_matches_package_rejected(self, doc_ids: set[str], root_ids: set[str]) -> None:
        ann = {"subject": "SPDXRef-Pkg-Dep"}
        assert spdx3_annotation_subject_matches(ann, doc_ids, root_ids) is False

    def test_empty_subject_with_root_accepted(self, doc_ids: set[str], root_ids: set[str]) -> None:
        ann = {"subject": ""}
        assert spdx3_annotation_subject_matches(ann, doc_ids, root_ids) is True

    def test_empty_subject_without_root_rejected(self, doc_ids: set[str]) -> None:
        ann = {"subject": ""}
        assert spdx3_annotation_subject_matches(ann, doc_ids, set()) is False

    def test_missing_subject_treated_as_empty(self, doc_ids: set[str], root_ids: set[str]) -> None:
        ann: dict[str, Any] = {}
        assert spdx3_annotation_subject_matches(ann, doc_ids, root_ids) is True
        assert spdx3_annotation_subject_matches(ann, doc_ids, set()) is False

    def test_annotationSubject_alias(self, doc_ids: set[str], root_ids: set[str]) -> None:
        """Some emitters use `annotationSubject` instead of `subject`."""
        ann = {"annotationSubject": "SPDXRef-Document"}
        assert spdx3_annotation_subject_matches(ann, doc_ids, root_ids) is True

    def test_non_string_subject_rejected(self, doc_ids: set[str], root_ids: set[str]) -> None:
        for bad in [None, 42, ["ref"], {"k": "v"}]:
            ann = {"subject": bad}
            assert spdx3_annotation_subject_matches(ann, doc_ids, root_ids) is False


# ============================================================================
# iter_spdx3_elements
# ============================================================================


class TestIterSpdx3Elements:
    def test_yields_dict_entries_from_graph(self) -> None:
        data = {"@graph": [{"type": "A"}, {"type": "B"}]}
        assert [e["type"] for e in iter_spdx3_elements(data)] == ["A", "B"]

    def test_yields_from_elements_alias(self) -> None:
        data = {"elements": [{"type": "A"}]}
        assert [e["type"] for e in iter_spdx3_elements(data)] == ["A"]

    def test_prefers_graph_over_elements(self) -> None:
        """When both are present, @graph wins (legacy alias is fallback only)."""
        data = {
            "@graph": [{"type": "from-graph"}],
            "elements": [{"type": "from-elements"}],
        }
        assert [e["type"] for e in iter_spdx3_elements(data)] == ["from-graph"]

    def test_non_dict_entries_skipped(self) -> None:
        data = {"@graph": ["str", None, {"type": "Only"}, 42]}
        assert [e["type"] for e in iter_spdx3_elements(data)] == ["Only"]

    def test_single_node_dict_graph(self) -> None:
        data = {"@graph": {"type": "Lonely"}}
        assert [e["type"] for e in iter_spdx3_elements(data)] == ["Lonely"]

    @pytest.mark.parametrize("bad", ["str", 42, None, True])
    def test_malformed_graph_yields_nothing(self, bad: Any) -> None:
        assert list(iter_spdx3_elements({"@graph": bad})) == []

    def test_missing_graph_and_elements_yields_nothing(self) -> None:
        assert list(iter_spdx3_elements({})) == []

    @pytest.mark.parametrize("bad", ["str", 42, None])
    def test_malformed_graph_falls_back_to_elements(self, bad: Any) -> None:
        """If `@graph` is present but unusable, the well-formed `elements`
        alias must still be honoured — otherwise a legacy emitter that
        set `@graph: null` alongside a valid `elements` payload would be
        treated as empty."""
        data = {"@graph": bad, "elements": [{"type": "FromElements"}]}
        assert [e["type"] for e in iter_spdx3_elements(data)] == ["FromElements"]

    def test_malformed_graph_and_malformed_elements_yields_nothing(self) -> None:
        """Both containers unusable → empty iteration, no raise."""
        data = {"@graph": "broken", "elements": 42}
        assert list(iter_spdx3_elements(data)) == []
