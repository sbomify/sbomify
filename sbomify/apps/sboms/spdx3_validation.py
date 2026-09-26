"""Strict validation of SPDX 3.0.x documents against the vendored schemas.

The official ``spdx_3.0.0-schema.json`` and ``spdx_3.0.1-schema.json`` ship in
this repo, each the shacl2code output published at
``spdx.org/schema/<version>/spdx-json-schema.json``; this module is their only
runtime consumer. The compiled validators are cached at module level: the
schemas declare Draft 2020-12 and compiling one per upload is measurable.

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

Two schemas, because 3.0.1 is a separate document rather than a relabelled
3.0.0. It renamed ``software_File.software_contentType`` to ``contentType``,
``SpdxDocument.imports`` to ``import`` and ``build_Build.build_parameters`` to
``build_parameter``, and added ``IndividualElement``, so a document correct
under one is refused by the other. ``validate_spdx_sbom`` in ``schemas.py``
picks the schema from the version a document claims, and legacy
``spdxVersion``/``elements`` documents, which declare themselves non-conformant
by shape, never get here. A formatting-only 3.0.x patch above 3.0.1 validates
against the 3.0.1 schema, whose ``specVersion`` is a semver pattern, not a
pinned constant.

``jsonschema`` names violations element by element rather than over the whole
document. The 3.0.0 root is a ``oneOf`` between the graph form and a single
object, so a bad element anywhere surfaces as the root failing both, with the
document itself as the message. ``jsonschema`` also costs up to 290 ms an
element under 3.0.0, so walking a graph in order to reach one bad element could
hold an upload for over a minute. The gate picks out the elements that fail, and
only those reach ``jsonschema``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

# One per SPDX 3 release, keyed by the version it defines.
SCHEMA_PATHS = {
    "3.0.0": SCHEMA_DIR / "spdx_3.0.0-schema.json",
    "3.0.1": SCHEMA_DIR / "spdx_3.0.1-schema.json",
}

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


def _load(schema_version: str) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA_PATHS[schema_version].read_text())
    return schema


@cache
def _gate(schema_version: str) -> Any:
    """Is this document valid. Compiled once per schema, a few hundred ms, then reused."""
    import fastjsonschema

    return fastjsonschema.compile(_load(schema_version))


@cache
def _enumerator(schema_version: str) -> Any:
    """Why it is not. Only built once something has already failed the gate."""
    from jsonschema import Draft202012Validator

    return Draft202012Validator(_load(schema_version))


@cache
def _element_enumerator(schema_version: str) -> Any:
    """Why one ``@graph`` element is not, against what the schema holds every element to."""
    from jsonschema import Draft202012Validator

    schema = _load(schema_version)
    return Draft202012Validator({**_graph_items(schema), "$defs": schema["$defs"]})


@cache
def _declared_properties(schema_version: str) -> dict[str, frozenset[str] | None]:
    """What the gate cannot check by itself. Derived once, then reused."""
    return _declared_properties_of(_load(schema_version))


@cache
def _pinned_context(schema_version: str) -> str:
    """The ``@context`` the schema requires, so one element can be gated alone."""
    context: str = _load(schema_version)["properties"]["@context"]["const"]
    return context


def _graph_items(schema: dict[str, Any]) -> dict[str, Any]:
    """What the schema holds every ``@graph`` element to, wherever its root
    keeps it: under ``then`` in 3.0.1, in the first ``oneOf`` branch in 3.0.0."""
    for branch in (schema.get("then"), *schema.get("oneOf", ())):
        if isinstance(branch, dict) and "@graph" in branch.get("properties", {}):
            items: dict[str, Any] = branch["properties"]["@graph"]["items"]
            return items
    raise ValueError("the schema defines no @graph elements")


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


def spdx3_schema_errors(document: dict[str, Any], schema_version: str, limit: int = 3) -> list[str]:
    """The first ``limit`` violations of the ``schema_version`` schema as
    ``pointer: message`` strings.

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
    gate = _gate(schema_version)
    declared = _declared_properties(schema_version)
    try:
        gate(document)
    except Exception:
        # Anything the gate rejects, including a document shaped so oddly the
        # compiled validator raises something of its own, goes to the
        # enumerator for messages a reader can act on.
        return _violations(document, schema_version, limit)
    if not _declares_every_property(document, declared):
        return _violations(document, schema_version, limit)
    return []


def _violations(document: dict[str, Any], schema_version: str, limit: int) -> list[str]:
    """The first ``limit`` violations, named. Only reached once one exists."""
    errors: list[str] = []
    for path, message in _faults(document, schema_version):
        # Pointer-shaped location labels for a human reader: tokens are
        # RFC 6901-escaped so a / or ~ in a property name stays one token,
        # and the document root reads as words rather than an empty string.
        path_parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
        pointer = "/" + "/".join(path_parts) if path_parts else "(document root)"
        errors.append(f"{pointer}: {message[:200]}")
        if len(errors) >= limit:
            break
    return errors


def _faults(document: dict[str, Any], schema_version: str) -> Iterator[tuple[list[Any], str]]:
    """Every violation as ``(path, message)``, the root's first and then each element's.

    The root is checked with an empty graph, which leaves it only its own
    faults, and each element on its own, which is all the schema checks of an
    element: JSON Schema cannot follow a reference from one to another. The
    two together are the whole schema for a document in graph form. An element
    goes to ``jsonschema`` only once the gate or the key check has refused it,
    gated alone under the ``@context`` the schema pins so a bad root cannot
    make every element look bad.
    """
    enumerator = _enumerator(schema_version)
    graph = document.get("@graph")
    if not isinstance(graph, list):
        for error in enumerator.iter_errors(document):
            yield list(error.absolute_path), error.message
        return
    for error in enumerator.iter_errors({**document, "@graph": []}):
        yield list(error.absolute_path), error.message
    gate = _gate(schema_version)
    declared = _declared_properties(schema_version)
    context = _pinned_context(schema_version)
    for index, element in enumerate(graph):
        alone = {"@context": context, "@graph": [element]}
        if _passes(gate, alone) and _declares_every_property(alone, declared):
            continue
        for error in _element_enumerator(schema_version).iter_errors(element):
            yield ["@graph", index, *error.absolute_path], error.message


def _passes(gate: Any, document: dict[str, Any]) -> bool:
    try:
        gate(document)
    except Exception:
        return False
    return True
