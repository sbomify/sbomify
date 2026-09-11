#!/usr/bin/env python3
"""Flatten Yocto's multi-document SPDX 2.2 output into a single SPDX 2.3 document.

Yocto's ``create-spdx-2.2`` class does not emit one SBOM per image. It emits a
tarball of ~one document per recipe/package plus a thin image document that
points at them through ``externalDocumentRefs``. That shape is faithful to the
build but useless as a single-file SBOM: uploading the image document on its own
yields exactly one component.

This script walks the ``externalDocumentRefs`` graph starting from the image
document, rewrites every cross-document reference into a document-local
``SPDXRef-``, and emits one SPDX 2.3 document describing the image.

Usage:
    ./bin/flatten_yocto_spdx.py <extracted-spdx-dir> <image-document.spdx.json> <output.json>

SPDX 2.3 is a backwards-compatible superset of 2.2, so no field-level migration
is needed beyond the version bump; the only semantic change is the flattening.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

# Document-level bookkeeping relationships. Once every document is merged into
# one there is a single SPDXRef-DOCUMENT, so these either become self-references
# (AMENDS) or duplicate the single top-level DESCRIBES.
DOC_LEVEL_TYPES = {"DESCRIBES", "DESCRIBED_BY", "AMENDS", "OTHER"}

# SPDX 2.3 clause 6.3: an identifier is "SPDXRef-" followed by letters, numbers,
# "." and "-" only.
_ID_SAFE = re.compile(r"[^A-Za-z0-9.\-]")

# A LicenseRef inside a licence expression, optionally scoped to another
# document: "DocumentRef-recipe-busybox:LicenseRef-bzip2-1.0.4".
_LICENSE_REF = re.compile(r"(?:(DocumentRef-[A-Za-z0-9.\-]+):)?(LicenseRef-[A-Za-z0-9.\-]+)")

# Package and file fields holding a licence expression or a list of them.
LICENSE_FIELDS = ("licenseConcluded", "licenseDeclared", "licenseInfoFromFiles", "licenseInfoInFiles")


def _slug(value: str) -> str:
    return _ID_SAFE.sub("-", value)


def load_index(spdx_dir: Path) -> dict[str, Path]:
    """Map documentNamespace -> file, from the index.json Yocto ships."""
    index = json.loads((spdx_dir / "index.json").read_text())
    return {d["documentNamespace"]: spdx_dir / d["filename"] for d in index["documents"]}


def collect(spdx_dir: Path, image_doc: Path) -> dict[str, dict]:
    """Breadth-first walk of externalDocumentRefs starting at the image document.

    Returns documents keyed by namespace. Documents unreachable from the image
    (native/build-only recipes that nothing in the rootfs depends on) are left
    out, so the result is the closure of the image rather than of the build.
    """
    by_namespace = load_index(spdx_dir)
    root = json.loads(image_doc.read_text())

    collected: dict[str, dict] = {root["documentNamespace"]: root}
    queue = [root]
    while queue:
        doc = queue.pop(0)
        for ref in doc.get("externalDocumentRefs", []):
            namespace = ref["spdxDocument"]
            if namespace in collected:
                continue
            path = by_namespace.get(namespace)
            if path is None or not path.exists():
                sys.stderr.write(f"warning: unresolved document reference {namespace}\n")
                continue
            child = json.loads(path.read_text())
            collected[namespace] = child
            queue.append(child)
    return collected


def build_id_map(collected: dict[str, dict], root_namespace: str) -> dict[tuple[str, str], str]:
    """Assign every element in every document a unique, document-local SPDXRef.

    Elements from the image document keep their original identifier; everything
    else is prefixed with its source document name so that, say, busybox's and
    base-files' ``SPDXRef-Package-...`` cannot collide.
    """
    id_map: dict[tuple[str, str], str] = {}
    for namespace, doc in collected.items():
        prefix = "" if namespace == root_namespace else f"{_slug(doc['name'])}-"
        for element in [*doc.get("packages", []), *doc.get("files", [])]:
            original = element["SPDXID"]
            id_map[(namespace, original)] = f"SPDXRef-{prefix}{original.removeprefix('SPDXRef-')}"
    return id_map


def build_license_map(collected: dict[str, dict]) -> tuple[dict[tuple[str, str], str], list[dict]]:
    """Merge every document's hasExtractedLicensingInfos into one list.

    Yocto scopes non-SPDX licences per document, so two recipes can legitimately
    define the same ``LicenseRef-`` id with different text. Ids are kept as-is
    when every document that defines them agrees on the text, and prefixed with
    the defining document's name only where they genuinely clash.
    """
    by_id: dict[str, list[tuple[str, dict]]] = {}
    for namespace, doc in collected.items():
        for entry in doc.get("hasExtractedLicensingInfos", []):
            by_id.setdefault(entry["licenseId"], []).append((namespace, entry))

    license_map: dict[tuple[str, str], str] = {}
    merged: dict[str, dict] = {}
    for license_id, definitions in by_id.items():
        ambiguous = len({d["extractedText"] for _, d in definitions}) > 1
        for namespace, entry in definitions:
            new_id = (
                f"LicenseRef-{_slug(collected[namespace]['name'])}-{license_id.removeprefix('LicenseRef-')}"
                if ambiguous
                else license_id
            )
            license_map[(namespace, license_id)] = new_id
            merged[new_id] = {**entry, "licenseId": new_id}
    return license_map, sorted(merged.values(), key=lambda e: e["licenseId"])


def rewrite_license(
    expression: str,
    namespace: str,
    license_map: dict[tuple[str, str], str],
    alias_to_namespace: dict[str, dict[str, str]],
) -> str:
    """Rewrite LicenseRefs in a licence expression to document-local ids."""

    def substitute(match: re.Match[str]) -> str:
        alias, license_id = match.group(1), match.group(2)
        target = alias_to_namespace[namespace].get(alias) if alias else namespace
        if target is None:
            return match.group(0)
        return license_map.get((target, license_id), match.group(0))

    return _LICENSE_REF.sub(substitute, expression)


def rewrite_licenses_in_place(
    element: dict,
    namespace: str,
    license_map: dict[tuple[str, str], str],
    alias_to_namespace: dict[str, dict[str, str]],
) -> None:
    for field in LICENSE_FIELDS:
        value = element.get(field)
        if isinstance(value, str):
            element[field] = rewrite_license(value, namespace, license_map, alias_to_namespace)
        elif isinstance(value, list):
            element[field] = [
                rewrite_license(item, namespace, license_map, alias_to_namespace) if isinstance(item, str) else item
                for item in value
            ]


def resolve(
    reference: str,
    doc: dict,
    namespace: str,
    id_map: dict[tuple[str, str], str],
    alias_to_namespace: dict[str, dict[str, str]],
) -> str | None:
    """Turn a possibly cross-document reference into a flattened SPDXRef.

    NONE/NOASSERTION are passed through untouched: Yocto uses
    ``GENERATED_FROM NOASSERTION`` with the source path in a comment to record
    debug-source provenance, and that is real build output worth keeping.

    Returns None for references that do not survive flattening: another
    document's SPDXRef-DOCUMENT, and any element that was not collected.
    """
    if reference in ("NONE", "NOASSERTION"):
        return reference
    if ":" in reference:
        alias, _, local_id = reference.partition(":")
        target_namespace = alias_to_namespace[namespace].get(alias)
        if target_namespace is None:
            return None
    else:
        target_namespace, local_id = namespace, reference
    if local_id == "SPDXRef-DOCUMENT":
        return None
    return id_map.get((target_namespace, local_id))


def flatten(spdx_dir: Path, image_doc: Path) -> dict:
    collected = collect(spdx_dir, image_doc)
    root = json.loads(image_doc.read_text())
    root_namespace = root["documentNamespace"]
    id_map = build_id_map(collected, root_namespace)

    alias_to_namespace = {
        namespace: {ref["externalDocumentId"]: ref["spdxDocument"] for ref in doc.get("externalDocumentRefs", [])}
        for namespace, doc in collected.items()
    }

    license_map, extracted_licenses = build_license_map(collected)

    packages: list[dict] = []
    files: list[dict] = []
    relationships: list[dict] = []
    seen_relationships: set[str] = set()

    for namespace, doc in collected.items():
        for package in doc.get("packages", []):
            package = dict(package)
            package["SPDXID"] = id_map[(namespace, package["SPDXID"])]
            if "hasFiles" in package:
                package["hasFiles"] = [
                    new_id
                    for file_id in package["hasFiles"]
                    if (new_id := resolve(file_id, doc, namespace, id_map, alias_to_namespace))
                    and new_id not in ("NONE", "NOASSERTION")
                ]
            rewrite_licenses_in_place(package, namespace, license_map, alias_to_namespace)
            packages.append(package)

        for file_entry in doc.get("files", []):
            file_entry = dict(file_entry)
            file_entry["SPDXID"] = id_map[(namespace, file_entry["SPDXID"])]
            rewrite_licenses_in_place(file_entry, namespace, license_map, alias_to_namespace)
            files.append(file_entry)

        for relationship in doc.get("relationships", []):
            source = resolve(relationship["spdxElementId"], doc, namespace, id_map, alias_to_namespace)
            target = resolve(relationship["relatedSpdxElement"], doc, namespace, id_map, alias_to_namespace)
            if source is None or target is None:
                # Dropped: document-level bookkeeping, or a reference into a
                # document outside the image closure.
                continue
            merged = dict(relationship)
            merged["spdxElementId"] = source
            merged["relatedSpdxElement"] = target
            # Identical documents can be reached twice; drop only exact repeats.
            key = json.dumps(merged, sort_keys=True)
            if key in seen_relationships:
                continue
            seen_relationships.add(key)
            relationships.append(merged)

    image_package_id = id_map[(root_namespace, root["packages"][0]["SPDXID"])]
    relationships.insert(
        0,
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": image_package_id,
        },
    )

    creation_info = dict(root["creationInfo"])
    creation_info["creators"] = [
        *creation_info.get("creators", []),
        "Tool: sbomify-flatten-yocto-spdx",
    ]
    creation_info["comment"] = (
        f"Flattened from the {len(collected)} SPDX 2.2 documents Yocto emitted for this image "
        "and re-declared as SPDX 2.3. Package, file, license and relationship data is verbatim "
        "from the Yocto build; only cross-document references were rewritten as document-local "
        "identifiers. See bin/flatten_yocto_spdx.py."
    )

    name = root["name"]
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": name,
        "documentNamespace": f"http://spdx.org/spdxdocs/{name}-{uuid.uuid5(uuid.NAMESPACE_URL, root_namespace)}",
        "creationInfo": creation_info,
        "documentDescribes": [image_package_id],
        "hasExtractedLicensingInfos": extracted_licenses,
        "packages": packages,
        "files": files,
        "relationships": relationships,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        sys.stderr.write(f"{__doc__}\n")
        return 2
    spdx_dir, image_doc, output = Path(argv[1]), Path(argv[2]), Path(argv[3])
    document = flatten(spdx_dir, image_doc)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    sys.stdout.write(
        f"{output}: {len(document['packages'])} packages, "
        f"{len(document['files'])} files, {len(document['relationships'])} relationships, "
        f"{len(document['hasExtractedLicensingInfos'])} extracted licenses\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
