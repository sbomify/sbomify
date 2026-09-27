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
refused there and nowhere else. So the gate compiles the schema with each of
those closures spelled out as the class's own list of property names, derived
from the schema once. That is exact, because an object's type decides its
class, and it makes the gate's verdict final: ``jsonschema`` only writes the
messages.

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
document itself as the message. Its cost also grows with an element's size
and with how deeply objects nest in it, so the gate picks out the elements that
fail and ``jsonschema`` itemises only what a budget allows. An element past the
budget is still named, without the itemised reason.
"""

from __future__ import annotations

import copy
import itertools
import json
from collections.abc import Callable, Iterator
from contextlib import suppress
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


@cache
def _load(schema_version: str) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA_PATHS[schema_version].read_text())
    return schema


@cache
def _gate(schema_version: str) -> Any:
    """Is this document valid. Compiled once per schema, a few hundred ms, then reused."""
    import fastjsonschema

    return fastjsonschema.compile(_closed(_load(schema_version)))


def _enumerator(schema_version: str, steps: Iterator[int]) -> Any:
    """Why it is not. Only built once something has already failed the gate."""
    return _metered(_load(schema_version), steps)


def _element_enumerator(schema_version: str, steps: Iterator[int]) -> Any:
    """Why one ``@graph`` element is not, against what the schema holds every element to."""
    schema = _load(schema_version)
    return _metered({**_graph_items(schema), "$defs": schema["$defs"]}, steps)


class _Spent(Exception):
    """The document's itemising steps ran out."""


def _metered(schema: dict[str, Any], steps: Iterator[int]) -> Any:
    """``jsonschema`` over ``schema``, taking one of ``steps`` for every keyword
    it evaluates and raising ``_Spent`` once ``_ITEMISED_STEPS`` are gone."""
    from jsonschema import Draft202012Validator
    from jsonschema.validators import extend

    def meter(keyword: Callable[..., Any]) -> Callable[..., Any]:
        def metered(validator: Any, value: Any, instance: Any, subschema: Any) -> Any:
            if next(steps) >= _ITEMISED_STEPS:
                raise _Spent
            return keyword(validator, value, instance, subschema)

        return metered

    keywords = {name: meter(keyword) for name, keyword in Draft202012Validator.VALIDATORS.items()}
    return extend(Draft202012Validator, keywords)(schema)  # type: ignore[no-untyped-call]


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
_GRAPH_FORM = ["@context", "@graph"]


def _declared_properties_of(schema: dict[str, Any]) -> dict[str, frozenset[str] | None]:
    """Per class an element may be, every property the schema evaluates on it.

    ``None`` marks a class the schema leaves open (``unevaluatedProperties:
    true``), whose instances may carry anything. A closed class must require
    ``type`` and pin it to its own name, so that no object can be two classes
    at once: the closed gate is exact only while that holds.
    """
    defs = schema["$defs"]

    def collect(node: dict[str, Any], names: set[str], required: set[str], types: list[Any]) -> bool:
        """Add what ``node`` evaluates to ``names``. False if it evaluates everything."""
        if node.get("unevaluatedProperties") is True:
            return False
        if unexpected := node.keys() - _CLASS_CHAIN_KEYWORDS:
            raise ValueError(f"cannot derive SPDX class properties through {sorted(unexpected)}")
        properties = node.get("properties", {})
        names.update(properties)
        required.update(node.get("required", ()))
        if "type" in properties:
            types.append(properties["type"])
        parts = list(node.get("allOf", ()))
        if "$ref" in node:
            parts.append(defs[node["$ref"].removeprefix("#/$defs/")])
        return all(collect(part, names, required, types) for part in parts)

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
        required: set[str] = set()
        types: list[Any] = []
        if not all(collect(part, names, required, types) for part in parts):
            declared[name] = None
            continue
        # The type pinned to the class's own name, as 3.0.1 and 3.0.0 spell it.
        pinned = ({"const": name}, {"oneOf": [{"const": name}]})
        if "type" not in required or not any(pin in types for pin in pinned):
            raise ValueError(f"{name}: its type does not decide the class")
        declared[name] = frozenset(names)
    return declared


def _closed(schema: dict[str, Any]) -> dict[str, Any]:
    """The schema with every ``unevaluatedProperties: false`` spelled out in
    keywords ``fastjsonschema`` enforces.

    Wherever the schema closes an object, each class the object may be becomes
    that class plus a ``propertyNames`` list of what the class declares, and
    the root takes only ``@context`` and ``@graph``. Exact for a document in
    graph form, because at most one class matches an object, except in two
    places where the gate is the stricter: a 3.0.0 root that is also an
    extension object, which the 3.0.0 root ``oneOf`` lets stand in for the
    whole graph, and a pattern-checked string ending in a newline (see
    ``test_the_gate_decides_even_where_jsonschema_cannot_say_why``). The
    ``@graph`` items schema also stops sitting beside a ``$ref``, where
    ``fastjsonschema`` drops every other keyword, so its ``type: object`` is
    enforced too.
    """
    declared = _declared_properties_of(schema)
    if any("@graph" in names for names in declared.values() if names is not None):
        raise ValueError("a class declares @graph, so the root cannot be closed to the graph form")
    closed = copy.deepcopy(schema)

    def close(member: dict[str, Any]) -> dict[str, Any]:
        name = member.get("$ref", "").removeprefix("#/$defs/")
        if name not in declared:
            raise ValueError(f"cannot close an object that may be {name or member}")
        names = declared[name]
        return member if names is None else {"allOf": [member, {"propertyNames": {"enum": sorted(names)}}]}

    closed["$defs"]["ClosedAnyClass"] = {"anyOf": [close(member) for member in closed["$defs"]["AnyClass"]["anyOf"]]}
    pending: list[Any] = [value for key, value in closed.items() if key != "$defs"] + list(closed["$defs"].values())
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            if node.get("unevaluatedProperties") is False:
                if node.get("$ref") == "#/$defs/AnyClass" and node.keys() <= {"type", "$ref", "unevaluatedProperties"}:
                    del node["$ref"]
                    node["allOf"] = [{"$ref": "#/$defs/ClosedAnyClass"}]
                elif "anyOf" in node and node.keys() <= {"type", "anyOf", "unevaluatedProperties"}:
                    node["anyOf"] = [close(member) for member in node["anyOf"]]
                else:
                    raise ValueError(f"cannot close {sorted(node)}")
            pending.extend(node.values())
    closed["propertyNames"] = {"enum": _GRAPH_FORM}
    return closed


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
    # the gate cannot be closed over.
    gate = _gate(schema_version)
    try:
        gate(document)
    except Exception:
        # Anything the gate rejects, including a document shaped so oddly the
        # compiled validator raises something of its own, is rejected, and goes
        # to the enumerator for messages a reader can act on.
        return _violations(document, schema_version, limit) or [f"(document root): {_refused(schema_version)}"]
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


# How much of a document ``jsonschema`` itemises. Its cost grows with a part's
# size, and faster with how deep objects nest inside it, since it evaluates
# every class a nested object might be at each level. Under 3.0.0 a small,
# shallow part can cost as much: its classes do not dispatch on ``type``, so it
# evaluates every class a value might be in full, once for each class declaring
# the property that holds the value. So each keyword it evaluates takes one of
# ``_ITEMISED_STEPS`` per document, and ``_faults`` names plainly any part not
# itemised when the steps run out. ``_itemisable_size`` applies the other three
# limits, to skip parts not worth starting. The text limit also keeps each step
# cheap, because a message quotes the value it is about. It counts an integer's
# digits too, since writing out a long integer costs more per digit the longer
# it is. Together they hold a rejection's messages to a second or so.
_ITEMISED_VALUES = 64
_ITEMISED_NESTING = 1
_ITEMISED_CHARACTERS = 4096
_ITEMISED_STEPS = 25_000


def _refused(schema_version: str) -> str:
    return f"not valid under the SPDX {schema_version} schema"


def _faults(document: dict[str, Any], schema_version: str) -> Iterator[tuple[list[Any], str]]:
    """Every violation as ``(path, message)``, part by part.

    ``jsonschema`` itemises each part the gate refuses while the budget lasts.
    Past that, or where it finds nothing the gate did, the part is named plainly.
    """
    budget, steps = _ITEMISED_VALUES, itertools.count()
    for path, value, enumerator in _refused_parts(document, schema_version):
        itemised = False
        if (size := _itemisable_size(value, budget)) is not None:
            budget -= size
            with suppress(_Spent):
                for error in enumerator(schema_version, steps).iter_errors(value):
                    itemised = True
                    yield [*path, *error.absolute_path], error.message
        if not itemised:
            yield path, _refused(schema_version)


def _refused_parts(
    document: dict[str, Any], schema_version: str
) -> Iterator[tuple[list[Any], Any, Callable[[str, Iterator[int]], Any]]]:
    """The parts of the document the gate refuses, each with the enumerator that can itemise it.

    The root is gated with an empty graph, which leaves it only its own faults,
    and each element on its own, which is all the schema checks of an element:
    JSON Schema cannot follow a reference from one to another. An element is
    gated under the ``@context`` the schema pins, so a bad root cannot make
    every element look bad.
    """
    gate = _gate(schema_version)
    graph = document.get("@graph")
    if not isinstance(graph, list):
        yield [], document, _enumerator
        return
    root = {**document, "@graph": []}
    if not _passes(gate, root):
        yield [], root, _enumerator
    context = _pinned_context(schema_version)
    for index, element in enumerate(graph):
        if not _passes(gate, {"@context": context, "@graph": [element]}):
            yield ["@graph", index], element, _element_enumerator


def _itemisable_size(part: Any, budget: int) -> int | None:
    """How many JSON values ``part`` holds, or None if ``jsonschema`` cannot
    itemise it cheaply: more than ``budget`` values, more than
    ``_ITEMISED_CHARACTERS`` characters in its keys, strings and integers, or objects
    nested deeper than ``_ITEMISED_NESTING`` levels below it."""
    count, characters, pending = 0, 0, [(part, 0)]
    while pending:
        value, level = pending.pop()
        count += 1
        if count > budget:
            return None
        if isinstance(value, str):
            characters += len(value)
        elif isinstance(value, int):
            # Its digits, give or take one, without writing it out: log10(2) is 0.30103.
            characters += value.bit_length() * 30103 // 100000 + 1
        elif isinstance(value, dict):
            if level > _ITEMISED_NESTING:
                return None
            characters += sum(len(key) for key in value)
            pending.extend((child, level + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, level) for child in value)
        if characters > _ITEMISED_CHARACTERS:
            return None
    return count


def _passes(gate: Any, document: dict[str, Any]) -> bool:
    try:
        gate(document)
    except Exception:
        return False
    return True
