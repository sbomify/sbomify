"""Strict validation of SPDX 3.0.1+ documents against the vendored schema.

The official 259 KB ``spdx_3.0.1-schema.json`` ships in this repo; this module
is its only runtime consumer. The compiled validator is cached at module
level — the schema declares Draft 2020-12 and compiling it per upload is
measurable.

Two validators, for two different questions. ``fastjsonschema`` compiles the
schema to Python once and answers "is this valid" in 84 ms for 500 elements,
against 2.3 s for the same walk under ``jsonschema``: the schema is ref-heavy
and ``jsonschema`` re-resolves those refs per element, which profiling showed as
half a million ``referencing.Resource`` constructions. It stops at the first
violation, though, and an API error is more useful naming a few. So the compiled
one is the gate, and ``jsonschema`` is asked only to enumerate messages once the
gate has already said no. A valid document, which is the common case and the one
that was paying 2.3 s, never touches it.

Only documents that claim 3.0.1 or later are held to it: 3.0.0 producers
(syft, sbom-tool, JFrog) predate the schema and there is no vendored 3.0.0
schema to hold them to, and legacy ``spdxVersion``/``elements`` documents
declare themselves non-conformant by shape. A formatting-only 3.0.x patch
above 3.0.1 validates cleanly — the schema's ``specVersion`` is a semver
pattern, not a pinned constant.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "spdx_3.0.1-schema.json"

# A valid document pays the full walk, so this bounds it. The compiled gate
# validates 500 elements in ~84 ms and 20,000 in ~3.4 s, so the number is no
# longer what keeps the request inside its budget; what it still decides is how
# much of a document is checked at all.
#
# Deliberately unchanged while the validator was swapped. Lifting it would
# change which documents are accepted, and that question is open separately:
# turning validation on over real Yocto output rejects a sizeable minority of
# documents, and the ceiling should move with that decision rather than with a
# performance change.
MAX_VALIDATED_ELEMENTS = 500


@cache
def _gate() -> Any:
    """Is this document valid. Compiled once, ~333 ms, then reused."""
    import fastjsonschema

    return fastjsonschema.compile(json.loads(SCHEMA_PATH.read_text()))


@cache
def _enumerator() -> Any:
    """Why it is not. Only built once something has already failed the gate."""
    from jsonschema import Draft202012Validator

    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def spdx3_schema_errors(document: dict[str, Any], limit: int = 3) -> list[str]:
    """The first ``limit`` schema violations as ``pointer: message`` strings.

    The full error list on a large document can run to thousands of entries;
    the first few name the offending property paths, which is what an API
    error response can usefully carry.

    Documents whose ``@graph`` exceeds ``MAX_VALIDATED_ELEMENTS`` are checked
    on that many elements only. The schema's checks are per-element (JSON
    Schema cannot follow cross-references), so validating a prefix is sound
    for what it covers and silent about the rest.
    """
    graph = document.get("@graph")
    if isinstance(graph, list) and len(graph) > MAX_VALIDATED_ELEMENTS:
        # The capped subset keeps the document-level elements first: the
        # SpdxDocument and CreationInfo entries carry the conformance claim
        # itself, and a producer that serializes them last would otherwise
        # have exactly those escape the check.
        def _is_document_level(element: object) -> bool:
            if not isinstance(element, dict):
                return False
            elem_type = element.get("type", element.get("@type", ""))
            if not isinstance(elem_type, str):
                return False
            tail = elem_type.rsplit("/", 1)[-1]
            return tail in ("SpdxDocument", "CreationInfo")

        core = [e for e in graph if _is_document_level(e)]
        rest = [e for e in graph if not _is_document_level(e)]
        document = {**document, "@graph": (core + rest)[:MAX_VALIDATED_ELEMENTS]}

    # Resolved before the try, deliberately. Building the gate inside it would
    # let an ImportError read as "this document is invalid": validation would
    # still be correct, every test would still pass, and the compiled path would
    # be silently off. A missing dependency has to be loud.
    gate = _gate()
    try:
        gate(document)
    except Exception:
        # Anything the gate rejects, including a document shaped so oddly the
        # compiled validator raises something of its own, goes to the
        # enumerator for messages a reader can act on.
        return _violations(document, limit)
    return []


def _violations(document: dict[str, Any], limit: int) -> list[str]:
    """The first ``limit`` violations, named. Only reached once one exists."""
    errors: list[str] = []
    for error in _enumerator().iter_errors(document):
        # Pointer-shaped location labels for a human reader: tokens are
        # RFC 6901-escaped so a / or ~ in a property name stays one token,
        # and the document root reads as words rather than an empty string.
        path_parts = [str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path]
        pointer = "/" + "/".join(path_parts) if path_parts else "(document root)"
        errors.append(f"{pointer}: {error.message[:200]}")
        if len(errors) >= limit:
            break
    return errors
