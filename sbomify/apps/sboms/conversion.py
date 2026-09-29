"""A scanner-readable copy of an SBOM, derived for one scan and thrown away.

The stored artifact is never modified (ADR-004), and the scanners do not read
every format sbomify accepts: osv-scanner has no SPDX 3 reader, and Dependency
Track takes CycloneDX only. Telling the uploader to convert the document by
hand is the workaround this module exists to stop shipping, so the scan path
derives a copy in a format the scanner knows, scans that, and reports the
findings against the original.

The copy carries what a scanner matches on and nothing else: a component per
package, with the purl and the CPE it was identified by. Everything else a
full converter would carry, among them files, relationships, licences and
the SPDX 3 security profile, is read from the stored original instead, which
is where it is accurate.

Written here rather than shelled out to a converter because nothing
off-the-shelf reads the format that is the problem. SPDX 3 is what the
scanners refuse, and protobom and cyclonedx-cli both stop at SPDX 2.3, while
the Python spdx-tools can write SPDX 3 and not read it. sbomify already reads
SPDX 3 in five plugins, so the copy is emitted from the same parse rather than
from a second toolchain with its own losses to patch up.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, ValidationError
from jsonschema.exceptions import best_match
from referencing import Registry
from referencing.jsonschema import DRAFT7

#: What the derived copy declares itself to be. Pinned rather than latest:
#: Dependency Track is the other consumer and reads 1.6.
CYCLONEDX_SPEC_VERSION = "1.6"
CYCLONEDX_1_6 = "CycloneDX-1.6"

#: External-reference types that name a package in SPDX 2.x, mapped to the
#: CycloneDX field that carries the same identifier.
_SPDX2_IDENTIFIERS = {
    "purl": "purl",
    "cpe22Type": "cpe",
    "cpe23Type": "cpe",
}

#: The same, for SPDX 3 external identifiers.
_SPDX3_IDENTIFIERS = {
    "packageUrl": "purl",
    "packageURL": "purl",
    "purl": "purl",
    "cpe22": "cpe",
    "cpe23": "cpe",
}


#: Where the official CycloneDX JSON schemas are vendored.
_CYCLONEDX_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

#: Rounds of pruning before giving up. Each round removes everything the
#: schema flagged, so a real document settles in two or three.
_MAX_PRUNE_ROUNDS = 10


class ConversionFailed(RuntimeError):
    """The document is not one this can express as CycloneDX."""


@functools.cache
def _cyclonedx_validator(version: str) -> Draft7Validator:
    """A validator for the vendored CycloneDX ``version`` JSON schema.

    The bom schema points at two side files that are not vendored: the SPDX
    licence id list and the JSF signature. Both are shared by every spec
    version, so moving a document between versions cannot change whether it
    meets them, and they are stood in for by their bare types.
    """
    schema = json.loads((_CYCLONEDX_SCHEMA_DIR / f"cdx_bom-{version}.schema.json").read_text())
    registry: Registry[Any] = Registry().with_resources(
        [
            ("http://cyclonedx.org/schema/spdx.schema.json", DRAFT7.create_resource({"type": "string"})),
            (
                "http://cyclonedx.org/schema/jsf-0.82.schema.json",
                DRAFT7.create_resource({"definitions": {"signature": {"type": "object"}}}),
            ),
        ]
    )
    return Draft7Validator(schema, registry=registry)


def downgrade_cyclonedx(data: bytes, version: str) -> bytes:
    """Return a copy of a CycloneDX JSON document that is valid at ``version``.

    For a scanner that refuses a newer spec version. Whatever the older schema
    does not define is dropped: properties it does not know, enum values it
    does not list, and a list entry left without a member it requires, a hash
    whose algorithm 1.6 does not name, say. The vendored schema is the only
    source of what "does not define" means, so no field list is kept here.

    Raises :class:`ConversionFailed` when the copy still does not validate,
    since uploading it would only trade one refusal for another.
    """
    try:
        document = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConversionFailed(f"not a JSON document: {exc}") from exc
    if not isinstance(document, dict) or document.get("bomFormat") != "CycloneDX":
        raise ConversionFailed("not a CycloneDX JSON document")

    document["specVersion"] = version
    document["$schema"] = f"http://cyclonedx.org/schema/bom-{version}.schema.json"
    validator = _cyclonedx_validator(version)
    for _ in range(_MAX_PRUNE_ROUNDS):
        errors = list(validator.iter_errors(document))
        if not errors:
            return json.dumps(document).encode("utf-8")
        cuts: set[tuple[str | int, ...]] = set()
        for error in errors:
            cuts.update(_cuts(error, top_level=True) or ())
        if not cuts:
            break
        # Deepest and highest index first, so a cut never shifts the position
        # of another still to be made in the same list.
        for path in sorted(cuts, key=lambda p: [(isinstance(k, str), k) for k in p], reverse=True):
            _delete(document, path)
    raise ConversionFailed(f"not valid CycloneDX {version}: {best_match(errors).message[:300]}")


def _cuts(error: ValidationError, *, top_level: bool) -> list[tuple[str | int, ...]] | None:
    """The paths to delete so ``error`` goes away, or ``None`` if it cannot."""
    path = tuple(error.absolute_path)
    schema, instance = error.schema, error.instance
    if (
        error.validator == "additionalProperties"
        and error.validator_value is False
        and isinstance(schema, dict)
        and isinstance(instance, dict)
    ):
        known = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        return [
            (*path, key)
            for key in instance
            if key not in known and not any(re.search(pattern, key) for pattern in patterns)
        ] or None
    if error.validator in ("enum", "const") and path:
        return [path]
    if error.validator == "required" and top_level:
        # The entry lost a member it cannot do without, so the entry goes. Only
        # an entry in a list: a required member of a lone object is structure.
        indexes = [i for i, key in enumerate(path) if isinstance(key, int)]
        return [path[: indexes[-1] + 1]] if indexes else None
    if error.validator in ("anyOf", "oneOf") and error.context:
        # Prune towards the alternative that needs the fewest cuts. Dropping
        # an entry is left out here: in the wrong alternative it would throw
        # away data the right one keeps.
        branches: dict[Any, list[ValidationError]] = {}
        for sub in error.context:
            branches.setdefault(sub.relative_schema_path[0], []).append(sub)
        best: list[tuple[str | int, ...]] | None = None
        for subs in branches.values():
            fixes = [_cuts(sub, top_level=False) for sub in subs]
            if all(fixes):
                flat = [cut for fix in fixes for cut in fix or ()]
                if best is None or len(flat) < len(best):
                    best = flat
        return best
    return None


def _delete(document: Any, path: tuple[str | int, ...]) -> None:
    """Remove the member at ``path``, if an earlier cut has not already."""
    parent = document
    for key in path[:-1]:
        try:
            parent = parent[key]
        except (KeyError, IndexError, TypeError):
            return
    try:
        del parent[path[-1]]
    except (KeyError, IndexError, TypeError):
        pass


def to_cyclonedx(data: bytes) -> bytes:
    """Return ``data`` re-expressed as a CycloneDX 1.6 document.

    Accepts SPDX 2.x and SPDX 3 JSON. Raises :class:`ConversionFailed` for
    anything else, and for a document that yields no component at all, because
    handing a scanner an empty bill would report as a clean scan.
    """
    try:
        document = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConversionFailed(f"not a JSON document: {exc}") from exc
    if not isinstance(document, dict):
        raise ConversionFailed(f"expected an object, got {type(document).__name__}")

    from sbomify.apps.plugins.builtins._spdx3_helpers import is_spdx3

    if is_spdx3(document):
        components = _components_from_spdx3(document)
        source = "SPDX-3.0"
    elif document.get("spdxVersion"):
        components = _components_from_spdx2(document)
        source = str(document.get("spdxVersion"))
    else:
        raise ConversionFailed("not an SPDX document")

    if not components:
        raise ConversionFailed(f"{source} document names no package to scan")

    return json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": CYCLONEDX_SPEC_VERSION,
            "version": 1,
            "metadata": {
                # Says what this is, so a copy that outlives its scan directory
                # cannot be mistaken for something a customer uploaded.
                "tools": {"components": [{"type": "application", "name": "sbomify", "group": "derived-for-scan"}]},
                "properties": [{"name": "sbomify:derived_from", "value": source}],
            },
            "components": components,
        }
    ).encode("utf-8")


def _component(ref: Any, name: Any, version: Any) -> dict[str, Any] | None:
    """The shared shape, or ``None`` for an entry that names nothing."""
    if not isinstance(name, str) or not name.strip():
        return None
    component: dict[str, Any] = {"type": "library", "name": name.strip()}
    if isinstance(ref, str) and ref:
        component["bom-ref"] = ref
    if isinstance(version, str) and version.strip():
        component["version"] = version.strip()
    return component


def _components_from_spdx3(document: dict[str, Any]) -> list[dict[str, Any]]:
    """A component per ``software_Package`` in the graph."""
    from sbomify.apps.plugins.builtins._spdx3_helpers import (
        iter_spdx3_external_identifiers,
        spdx3_package_purl,
    )
    from sbomify.apps.plugins.builtins._spdx_shared import iter_spdx3_elements

    components: list[dict[str, Any]] = []
    for element in iter_spdx3_elements(document):
        if not isinstance(element, dict):
            continue
        # The tail alone: a type arrives as a full IRI, as security:Foo, or in
        # the underscore form, and only the class name is stable across them.
        tail = str(element.get("type") or element.get("@type") or "").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        if tail not in ("software_Package", "Package"):
            continue
        component = _component(
            element.get("spdxId") or element.get("@id"),
            element.get("name"),
            element.get("software_packageVersion"),
        )
        if component is None:
            continue
        purl = spdx3_package_purl(element)
        if purl:
            component["purl"] = purl
        for ext in iter_spdx3_external_identifiers(element):
            field = _SPDX3_IDENTIFIERS.get(str(ext.get("externalIdentifierType") or "").rsplit("/", 1)[-1])
            identifier = ext.get("identifier")
            if field and field not in component and isinstance(identifier, str) and identifier:
                component[field] = identifier
        components.append(component)
    return components


def _reference_type(value: Any) -> str:
    """The external-reference type, with the vocabulary URI stripped off.

    SPDX 2.x lets a referenceType be written as the bare term or as the full
    IRI it abbreviates. Yocto writes the IRI for every reference it emits, so
    a lookup against the bare terms alone finds none of them and the CPE that
    is the only identifier a Yocto package carries is dropped on the way
    through.
    """
    text = str(value or "")
    return text.rsplit("/", 1)[-1]


def _components_from_spdx2(document: dict[str, Any]) -> list[dict[str, Any]]:
    """A component per package, with the identifiers its external refs name."""
    packages = document.get("packages")
    if not isinstance(packages, list):
        return []

    components: list[dict[str, Any]] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        component = _component(package.get("SPDXID"), package.get("name"), package.get("versionInfo"))
        if component is None:
            continue
        # Not in the spec, which puts identifiers in externalRefs, but
        # producers write it and the plugins here already read it.
        purl = package.get("purl")
        if isinstance(purl, str) and purl:
            component["purl"] = purl
        refs = package.get("externalRefs")
        for ref in refs if isinstance(refs, list) else []:
            if not isinstance(ref, dict):
                continue
            field = _SPDX2_IDENTIFIERS.get(_reference_type(ref.get("referenceType")))
            locator = ref.get("referenceLocator")
            if field and field not in component and isinstance(locator, str) and locator:
                component[field] = locator
        components.append(component)
    return components
