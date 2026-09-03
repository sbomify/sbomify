"""A scanner-readable copy of an SBOM, derived for one scan and thrown away.

The stored artifact is never modified (ADR-004), and the scanners do not read
every format sbomify accepts: osv-scanner has no SPDX 3 reader, and Dependency
Track takes CycloneDX only. Telling the uploader to convert the document by
hand is the workaround this module exists to stop shipping, so the scan path
derives a copy in a format the scanner knows, scans that, and reports the
findings against the original.

The conversion is lossy by construction, and that is survivable because of
what the scanners actually read. They match on package identity, so a copy
carrying the packages and their purls is enough for the scan; the profile data
a converter drops, SPDX 3 security statements among it, is read from the
stored original instead.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, input is a temp file we wrote
import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

#: Target formats, spelled the way the converter names them on its command line.
#: The CycloneDX target is pinned to 1.6: the converter emits 1.7 by default and
#: Dependency Track is the consumer.
SPDX_2_3_JSON = "spdx-json"
CYCLONEDX_1_6_JSON = "cyclonedx-json@1.6"

DEFAULT_TIMEOUT_SECONDS = 120

#: What a document of each target format must say about itself. A converter
#: that writes an error object, an empty object or a bare list has produced
#: valid JSON and no SBOM, and handing that to a scanner would report a
#: conversion failure as a scanner fault.
_TARGET_MARKERS: dict[str, tuple[str, str | None]] = {
    SPDX_2_3_JSON: ("spdxVersion", None),
    CYCLONEDX_1_6_JSON: ("bomFormat", "CycloneDX"),
}


class ConversionUnavailable(RuntimeError):
    """No converter is installed, so the caller keeps whatever it did before."""


class ConversionFailed(RuntimeError):
    """The converter ran and would not read the document."""


def converter_path() -> str | None:
    """The converter binary, or ``None`` when it is not installed.

    Separated from :func:`convert_sbom` so a caller can decide what to do about
    a missing converter before it has a document in hand.
    """
    configured = getattr(settings, "SBOM_CONVERTER_PATH", "") or "syft"
    # which() alone, deliberately. It resolves a bare name on PATH and takes a
    # path as given, and it checks the file is executable. Falling back to "is
    # there a file by this name" would let a syft sitting in the working
    # directory answer for the bare default.
    return shutil.which(configured)


def convert_sbom(data: bytes, target_format: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    """Return ``data`` re-encoded as ``target_format``.

    Raises :class:`ConversionUnavailable` when no converter is installed and
    :class:`ConversionFailed` when one is but will not read this document.
    Callers distinguish the two: the first is a deployment that cannot convert
    and should degrade to its old behaviour, the second is a document nothing
    can do anything with.
    """
    binary = converter_path()
    if binary is None:
        raise ConversionUnavailable("no SBOM converter is installed")

    with tempfile.TemporaryDirectory(prefix="sbom-convert-") as workdir:
        # Written to a file rather than piped: the converter reads stdin only
        # when told to, and a real path keeps its error messages legible.
        source = Path(workdir) / "source.json"
        source.write_bytes(data)
        argv = [binary, "convert", str(source), "-o", target_format]
        try:
            # The scanner flags every subprocess call and asks for an audit,
            # and its inline suppression is not honoured in this repo, so the
            # audit is written here instead: argv is a fixed list run with
            # shell=False, so nothing in it is interpreted as a command.
            # The binary is an operator setting rather than anything a request
            # supplies, the source is a path this function just created, and
            # the format is one of the module constants above.
            completed = subprocess.run(  # nosec B603
                argv,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionFailed(f"conversion timed out after {timeout}s") from exc
        except OSError as exc:
            raise ConversionUnavailable(f"converter could not be run: {exc}") from exc

    stdout = completed.stdout or b""
    # The converter reports a document it cannot read on stderr and still exits
    # 0, so the body is the reliable failure signal rather than the return code.
    # Parsed rather than sniffed: output that merely starts like JSON can still
    # be truncated, and handing that to a scanner turns a conversion failure
    # into what looks like a scanner fault.
    if completed.returncode == 0 and stdout.strip():
        try:
            converted = json.loads(stdout)
        except ValueError as exc:
            raise ConversionFailed(f"converter produced no usable document: {exc}") from exc
        _require_target_shape(converted, target_format)
        try:
            source = json.loads(data)
        except ValueError:
            # The converter read it, so this only means we cannot, and the
            # conversion itself still stands.
            return stdout
        if isinstance(converted, dict) and _restore_cpes(source, converted):
            return json.dumps(converted).encode()
        return stdout
    detail = (completed.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    raise ConversionFailed(detail[-1] if detail else f"converter exited {completed.returncode}")


#: Where a CPE hides, by format. SPDX 3 writes external identifiers, SPDX 2.x
#: writes external refs, and both spell the type more than one way.
_CPE_IDENTIFIER_TYPES = frozenset({"cpe22", "cpe23", "cpe22Type", "cpe23Type"})


def _spdx_reference_type(cpe: str) -> str | None:
    """The SPDX 2.x reference type a CPE value belongs under, read off the value.

    The value decides, not the type the source labelled it with: a 2.3 string
    filed as ``cpe22`` is still a 2.3 string, and an SPDX reader checks the
    locator against the type it is filed under.
    """
    if cpe.startswith("cpe:2.3:"):
        return "cpe23Type"
    if cpe.startswith("cpe:/"):
        return "cpe22Type"
    return None


def _entries(container: Any, key: str) -> list[Any]:
    """The list at ``key``, or nothing.

    Both documents here are third-party: one came from an uploader, the other
    from the converter. A non-list where the spec says list is not something
    to iterate. An int raises TypeError and a string iterates its characters,
    so ``or []`` guards neither.
    """
    if not isinstance(container, dict):
        return []
    value = container.get(key)
    return value if isinstance(value, list) else []


def _package_key(name: Any, version: Any) -> tuple[str, str] | None:
    """What a package is called, as the two documents can agree on it.

    Name and version rather than the purl: the purl is exactly what a
    document lacking a usable one does not have, which is the case this
    exists for.

    Only ``None`` counts as no version. A numeric ``0`` is a version a
    document can state, and folding it to the empty string stopped it
    matching the ``"0"`` the converter writes, which lost the CPE for that
    package. A name that is only whitespace is no name, rather than a key
    every such package would share.
    """
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    return cleaned.lower(), "" if version is None else str(version).strip()


def _cpes_in_source(document: Any) -> dict[tuple[str, str], list[str]]:
    """Every CPE the source document states, keyed by package."""
    if not isinstance(document, dict):
        return {}
    found: dict[tuple[str, str], list[str]] = {}

    def record(name: Any, version: Any, values: list[str]) -> None:
        # Deduplicated, order preserved: a document may state the same CPE
        # under both external-identifier spellings, and a package is not more
        # identified for having said it twice. The SPDX side would otherwise
        # write the ref twice and the CycloneDX side picks the first.
        key = _package_key(name, version)
        if not (key and values):
            return
        seen = found.setdefault(key, [])
        seen.extend(cpe for cpe in values if cpe not in seen)

    def cpes_from(entries: Any, type_field: str, value_field: str) -> list[str]:
        values = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get(type_field) or "").rsplit("/", 1)[-1].rsplit("_", 1)[-1]
            value = entry.get(value_field)
            if kind in _CPE_IDENTIFIER_TYPES and isinstance(value, str) and value.startswith("cpe:"):
                values.append(value)
        return values

    # SPDX 3: elements in the graph.
    for element in _entries(document, "@graph"):
        # Packages only. A graph carries SpdxDocument, Relationship and Agent
        # elements too, and one of those sharing a name with a package would
        # otherwise hand it a CPE that was never about it. Same test the rest
        # of the SPDX 3 readers use.
        if not isinstance(element, dict) or element.get("type") != "software_Package":
            continue
        record(
            element.get("name"),
            element.get("software_packageVersion"),
            cpes_from(element.get("externalIdentifier"), "externalIdentifierType", "identifier"),
        )

    # SPDX 2.x: packages with external refs.
    for package in _entries(document, "packages"):
        if isinstance(package, dict):
            record(
                package.get("name"),
                package.get("versionInfo"),
                cpes_from(package.get("externalRefs"), "referenceType", "referenceLocator"),
            )
    return found


def _restore_cpes(source: Any, converted: dict[str, Any]) -> bool:
    """Put back the CPEs the converter dropped. True when anything changed.

    A converter carries purls across and loses the CPE, and for a build
    system that names its packages with a purl type no scanner maps, such as
    Yocto's ``pkg:yocto``, the CPE is the only identifier a scanner can match
    on. Losing it in a copy made for scanning is losing the scan.
    """
    cpes = _cpes_in_source(source)
    if not cpes:
        return False
    changed = False

    for package in _entries(converted, "packages"):
        if not isinstance(package, dict):
            continue
        key = _package_key(package.get("name"), package.get("versionInfo"))
        if not (key and cpes.get(key)):
            continue
        # A converter is a third party, so what it wrote where a list belongs
        # is not this function's to trust: anything else is replaced rather
        # than iterated. Losing a malformed value costs nothing, since a CPE
        # cannot be hiding in one.
        refs = package.get("externalRefs")
        if not isinstance(refs, list):
            refs = []
            package["externalRefs"] = refs
        present = {r.get("referenceLocator") for r in refs if isinstance(r, dict)}
        for cpe in cpes[key]:
            reference_type = _spdx_reference_type(cpe)
            if reference_type and cpe not in present:
                refs.append({"referenceCategory": "SECURITY", "referenceType": reference_type, "referenceLocator": cpe})
                present.add(cpe)
                changed = True

    for component in _entries(converted, "components"):
        if not isinstance(component, dict) or component.get("cpe"):
            continue
        key = _package_key(component.get("name"), component.get("version"))
        # CycloneDX carries one cpe per component, so the first is the one.
        for cpe in cpes.get(key, []) if key else []:
            component["cpe"] = cpe
            changed = True
            break
    return changed


def _require_target_shape(document: Any, target_format: str) -> None:
    """Raise unless the document says it is the format we asked for.

    Syntax is not enough: valid JSON that is not an SBOM would travel on to a
    scanner, which would then report the conversion's failure as its own. The
    check is the one field the format states about itself, not a schema
    validation, because this is a converter's own output rather than an
    upload and the strict validation already runs at the upload boundary.
    """
    marker = _TARGET_MARKERS.get(target_format)
    if marker is None:
        return
    field, expected = marker
    if not isinstance(document, dict):
        raise ConversionFailed(
            f"converter produced no usable document: expected an object, got {type(document).__name__}"
        )
    value = document.get(field)
    if not value or (expected is not None and value != expected):
        raise ConversionFailed(f"converter produced no usable document: no {field} in the output")
