"""Shared SPDX helpers used by multiple compliance plugins.

Covers both SPDX 2.x and SPDX 3.x. FDA and CISA plugins share this
module so their interpretation of SPDX 2.3 §12 (annotation subject
scope) and SPDX 3.0.1 rootElement semantics stay consistent.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from sbomify.apps.plugins.builtins._spdx3_helpers import is_spdx3
from sbomify.logging import getLogger

logger = getLogger(__name__)


def iter_spdx3_elements(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield well-formed SPDX 3.x elements from `@graph` (or the `elements`
    alias). Non-dict entries and non-list containers are skipped rather
    than raised — a hostile / malformed SBOM cannot crash the plugin.

    Container selection: prefer `@graph` when it is a list or single-node
    dict; otherwise fall back to the `elements` alias when *it* is a list
    or single-node dict. Only when both containers are unusable do we
    emit a single DEBUG log so operators can correlate a "nothing matched"
    finding with malformed input. This prevents a malformed `@graph`
    (``null``, string, int) from hiding a perfectly valid ``elements``
    container — the behaviour the docstring promises.
    """
    graph_container = data.get("@graph")
    alias_container = data.get("elements")

    def _normalise(container: Any) -> list[dict[str, Any]] | None:
        if isinstance(container, list):
            return container
        if isinstance(container, dict):
            return [container]
        return None

    raw_elements = _normalise(graph_container)
    if raw_elements is None:
        raw_elements = _normalise(alias_container)
    if raw_elements is None:
        # Only log when BOTH containers are unusable. Missing `@graph` with
        # a valid `elements` is a legacy SPDX 3.0 emitter, not an error.
        if graph_container is not None or alias_container is not None:
            logger.debug(
                "SPDX 3.x @graph/elements has unexpected types @graph=%s elements=%s; treating as empty element list",
                type(graph_container).__name__,
                type(alias_container).__name__,
            )
        return
    for element in raw_elements:
        if isinstance(element, dict):
            yield element


#: The external-reference types that identify a package, bare. SPDX 2.x also
#: allows each written as the full IRI it abbreviates, which is what
#: spdx2_reference_type strips before comparing.
SPDX2_IDENTIFIER_TYPES = frozenset({"purl", "cpe22Type", "cpe23Type", "swid"})


def spdx2_reference_type(ref: Any) -> str:
    """The bare external-reference type, whatever spelling the document used.

    SPDX 2.x permits ``referenceType`` as the bare term or as the full IRI it
    abbreviates, and the two mean the same thing. Yocto writes only the IRI:
    every one of the 108 external references in the Yocto Project's 5.0.5
    release SBOM is ``http://spdx.org/rdf/references/cpe23Type``, so comparing
    against bare terms alone scored an entire build as carrying no identifiers.

    Returns "" for anything that is not a reference with a string type, so a
    caller can compare the result without checking the shape first.
    """
    if not isinstance(ref, dict):
        return ""
    value = ref.get("referenceType")
    if not isinstance(value, str):
        return ""
    return value.rsplit("/", 1)[-1]


def spdx2_yocto_source_downloads(data: dict[str, Any]) -> frozenset[str]:
    """SPDXIDs of the source downloads in a Yocto recipe document.

    Beside every recipe package, Yocto's ``create-spdx`` class emits one
    package per fetched source: SPDXID ``SPDXRef-Download-<recipe>-<n>``,
    name ``<recipe>-source-<n>``, a URL ``downloadLocation`` (a release
    tarball, or ``git+https`` for a git fetch) and, for tarballs, a SHA256. It
    names where the recipe's source came from, has no purl, CPE or SWID, and
    no producer can give it one. So it is exempt from the per-package
    identifier check, as ``type=file`` components are on the CycloneDX side.

    All three must hold, so an ordinary package is never exempted: the
    document is written by OpenEmbedded's ``create-spdx``, the SPDXID has the
    ``SPDXRef-Download-`` prefix, and ``downloadLocation`` names a location.
    Empty for any other document.
    """
    creation_info = data.get("creationInfo")
    creators = creation_info.get("creators") if isinstance(creation_info, dict) else None
    if not isinstance(creators, list) or not any(
        isinstance(c, str) and c.startswith("Tool: OpenEmbedded Core create-spdx") for c in creators
    ):
        return frozenset()
    packages = data.get("packages")
    if not isinstance(packages, list):
        return frozenset()
    return frozenset(
        p["SPDXID"]
        for p in packages
        if isinstance(p, dict)
        and isinstance(p.get("SPDXID"), str)
        and p["SPDXID"].startswith("SPDXRef-Download-")
        and isinstance(p.get("downloadLocation"), str)
        and p["downloadLocation"].strip().upper() not in ("", "NOASSERTION", "NONE")
    )


def spdx2_root_spdxid(data: dict[str, Any]) -> str | None:
    """Return the SPDXID of the BOM subject for an SPDX 2.x document.

    Prefers documentDescribes[0]. Falls back to the first DESCRIBES
    relationship whose spdxElementId is SPDXRef-DOCUMENT.

    Returns None when no root can be identified.
    """
    describes = data.get("documentDescribes")
    if isinstance(describes, list) and describes:
        first = describes[0]
        if isinstance(first, str) and first:
            return first
    relationships = data.get("relationships") or []
    if not isinstance(relationships, list):
        return None
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        if str(rel.get("relationshipType") or "").upper() != "DESCRIBES":
            continue
        if rel.get("spdxElementId") != "SPDXRef-DOCUMENT":
            continue
        related = rel.get("relatedSpdxElement")
        if isinstance(related, str) and related:
            return related
    return None


def spdx2_annotation_targets_document(annotation: dict[str, Any], root_spdxid: str | None) -> bool:
    """Return True if a top-level SPDX 2.x annotation describes the
    document or the BOM subject (root).

    Per SPDX 2.3 §12 Annotation, an annotation with spdxElementId pointing
    at a specific package describes that package, not the document — so
    such annotations must not satisfy the narrow doc-level fallback.

    Lenient-but-safe handling of empty / missing spdxElementId:
    - Empty is accepted as document-scoped only when the document declares
      a DESCRIBES target (root_spdxid is not None). Real-world SPDX tools
      often omit spdxElementId on document-level annotations and pair
      them with a DESCRIBES relationship, so this preserves interoperability.
    - When the document has no DESCRIBES target, an annotation without an
      explicit spdxElementId is ambiguous and must be rejected so a crafted
      SBOM cannot inflate the compliance score via an unanchored annotation.
    """
    subject = annotation.get("spdxElementId", "")
    if not isinstance(subject, str):
        return False
    if subject == "SPDXRef-DOCUMENT":
        return True
    if subject == "":
        return root_spdxid is not None
    return root_spdxid is not None and subject == root_spdxid


def spdx3_document_subjects(data: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return (document_ids, root_element_ids) for an SPDX 3.x document.

    Per SPDX 3.0.1 Core.SpdxDocument:
      - spdxId of the SpdxDocument element itself identifies the document.
      - rootElement lists the "interesting" element(s) of the contained tree
        (the BOM subject). The spec explicitly forbids rootElement being
        of type SpdxDocument, so the two sets are disjoint by design.

    Returning them separately lets callers enforce stricter scoping rules
    (e.g. "empty-subject annotation is document-scoped only when at least
    one rootElement has been declared" — analogous to SPDX 2.x requiring
    a DESCRIBES target before lenient empty-subject handling kicks in).

    Defensive against malformed input: hostile SBOMs may set @graph to
    non-list values or individual elements to non-dicts. Such entries are
    skipped rather than allowed to raise AttributeError / TypeError out
    of the plugin.
    """
    document_ids: set[str] = set()
    root_element_ids: set[str] = set()
    for element in iter_spdx3_elements(data):
        elem_type = element.get("type", element.get("@type", ""))
        if not isinstance(elem_type, str) or "SpdxDocument" not in elem_type:
            continue
        doc_id = element.get("spdxId", element.get("@id", ""))
        if isinstance(doc_id, str) and doc_id:
            document_ids.add(doc_id)
        roots = element.get("rootElement") or []
        # JSON-LD 1.1 compact form: an `@container: @set` property with a
        # single value may be serialised as a bare string rather than a
        # single-item array. Accept both forms so we don't miss a real
        # rootElement on a spec-legal compact document.
        if isinstance(roots, str):
            roots = [roots]
        if not isinstance(roots, list):
            continue
        for root in roots:
            if isinstance(root, str) and root:
                root_element_ids.add(root)
    return document_ids, root_element_ids


def spdx3_annotation_subject_matches(
    element: dict[str, Any],
    document_ids: set[str],
    root_element_ids: set[str],
) -> bool:
    """Return True if an SPDX 3.x Annotation targets the document or
    one of its rootElements.

    Empty subject is accepted as document-scoped only when at least one
    rootElement has been declared. This mirrors the SPDX 2.x rule that
    empty spdxElementId is only acceptable when a DESCRIBES target
    exists. Without any rootElement the annotation is unanchored — a
    malformed / crafted SBOM can't inflate the compliance score by
    dropping in a subject-less annotation.

    Both sets are accepted as valid subjects (`document_ids` covers the
    SpdxDocument's own spdxId, `root_element_ids` covers the declared
    BOM subject). Callers that need strict BOM-subject scoping should
    consult `root_element_ids` directly instead of using this helper.
    """
    subject = element.get("subject", element.get("annotationSubject", ""))
    if not isinstance(subject, str):
        return False
    if subject == "":
        return bool(root_element_ids)
    return subject in document_ids or subject in root_element_ids


def detect_format(sbom_data: dict[str, Any]) -> str:
    """Detect SBOM format from the data.

    Returns:
        Format string: "spdx", "spdx3", "cyclonedx", or "unknown".
    """
    if is_spdx3(sbom_data):
        return "spdx3"
    elif "spdxVersion" in sbom_data:
        return "spdx"
    elif isinstance(sbom_data.get("bomFormat"), str) and sbom_data["bomFormat"].lower() == "cyclonedx":
        return "cyclonedx"
    elif "specVersion" in sbom_data and "components" in sbom_data:
        # CycloneDX without explicit bomFormat
        return "cyclonedx"
    return "unknown"


def is_valid_timestamp(timestamp: str | None) -> bool:
    """Validate that a timestamp is in valid ISO-8601 format."""
    if not timestamp:
        return False
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return True
    except (ValueError, TypeError):
        return False
