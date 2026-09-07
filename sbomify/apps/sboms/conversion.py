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

import json
from typing import Any

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


class ConversionFailed(RuntimeError):
    """The document is not one this can express as CycloneDX."""


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
            field = _SPDX2_IDENTIFIERS.get(str(ref.get("referenceType") or ""))
            locator = ref.get("referenceLocator")
            if field and field not in component and isinstance(locator, str) and locator:
                component[field] = locator
        components.append(component)
    return components
