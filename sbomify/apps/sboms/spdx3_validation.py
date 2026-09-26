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

``fastjsonschema`` stops at draft-07 and skips ``unevaluatedProperties``, a
2019-09 keyword, without a word. That keyword is the only way the schema closes
an element or an inline object: a property its class does not declare is
refused there and nowhere else. So the gate also checks every object's keys
against what its class declares, derived from the schema once. A key it does not
find there sends the document to ``jsonschema``, whose verdict stands, so the
key check can cost a slow walk but never a rejection ``jsonschema`` would not
make.

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


@cache
def _declared_properties() -> dict[str, frozenset[str] | None]:
    """What the gate cannot check by itself. Derived once, then reused."""
    return _declared_properties_of(json.loads(SCHEMA_PATH.read_text()))


# What a schema node between a class and its properties may say. Anything that
# could make a property conditional, an anyOf, a oneOf, a not or a nested if, is
# refused: collecting through it would credit the class with properties only
# some instances may carry, and that overcount is a document waved through.
_CLASS_CHAIN_KEYWORDS = frozenset({"type", "properties", "required", "allOf", "$ref"})

# The root of a document in graph form, the only form SPDX3Schema lets reach
# this module: the schema evaluates these two keys there and nothing else.
_GRAPH_FORM = frozenset({"@context", "@graph"})


def _declared_properties_of(schema: dict[str, Any]) -> dict[str, frozenset[str] | None]:
    """Per class an element may be, every property the schema evaluates on it.

    ``None`` marks a class the schema leaves open (``unevaluatedProperties:
    true``), whose instances may carry anything.
    """
    defs = schema["$defs"]

    def collect(node: dict[str, Any], names: set[str]) -> bool:
        """Add what ``node`` evaluates to ``names``. False if it evaluates everything."""
        if node.get("unevaluatedProperties") is True:
            return False
        if unexpected := node.keys() - _CLASS_CHAIN_KEYWORDS:
            raise ValueError(f"cannot derive SPDX class properties through {sorted(unexpected)}")
        names.update(node.get("properties", ()))
        parts = list(node.get("allOf", ()))
        if "$ref" in node:
            parts.append(defs[node["$ref"].removeprefix("#/$defs/")])
        return all(collect(part, names) for part in parts)

    declared: dict[str, frozenset[str] | None] = {}
    for member in defs["AnyClass"]["anyOf"]:
        name = member["$ref"].removeprefix("#/$defs/")
        node = defs[name]
        parts = [node]
        if "if" in node:
            # Dispatch on type: "if" names the class and "else" is a string no
            # object can equal, so an instance only ever passes through "then".
            if node.keys() != {"if", "then", "else"} or node["else"].keys() != {"const"}:
                raise ValueError(f"cannot derive SPDX class properties for {name}")
            parts = [node["if"], node["then"]]
        names: set[str] = set()
        declared[name] = frozenset(names) if all(collect(part, names) for part in parts) else None
    return declared


def _declares_every_property(document: dict[str, Any], declared: dict[str, frozenset[str] | None]) -> bool:
    """Whether every key in the document is one its object's class declares.

    Run after the gate, so every object the schema closes is already an
    instance of a class it knows. One whose type names no closed class is an
    extension, which the schema leaves open and Yocto 6.0 writes, or sits
    where nothing is closed: its own keys go unchecked, and what it holds is
    still walked.
    """
    if not document.keys() <= _GRAPH_FORM:
        return False
    pending: list[Any] = [document.get("@graph")]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            node_type = node.get("type")
            allowed = declared.get(node_type) if isinstance(node_type, str) else None
            if allowed is not None and not node.keys() <= allowed:
                return False
            pending.extend(node.values())
    return True


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
    # be silently off. A missing dependency has to be loud, and so does a schema
    # the key check cannot read.
    gate = _gate()
    declared = _declared_properties()
    try:
        gate(document)
    except Exception:
        # Anything the gate rejects, including a document shaped so oddly the
        # compiled validator raises something of its own, goes to the
        # enumerator for messages a reader can act on.
        return _violations(document, limit)
    if not _declares_every_property(document, declared):
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
