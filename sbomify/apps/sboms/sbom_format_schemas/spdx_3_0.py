"""Legacy SPDX 3 normalization.

This module once held 531 lines of typed SPDX 3 models (SPDX3Document plus
Element subclasses) that nothing imported — the live parser is the lenient
SPDX3Schema in ``sbomify.apps.sboms.schemas``, spec conformance is enforced
by the vendored official JSON schema (``spdx3_validation``), and field
extraction lives in ``sbomify.apps.plugins.builtins._spdx3_helpers``. The
one thing still in use is the legacy-format normalizer below.
"""

from typing import Any

SPDX_30_CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"


def _normalize_legacy_to_graph(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy SPDX 3.0 format (spdxVersion/elements) to @context/@graph.

    In legacy format, the root object acts as the SpdxDocument with fields like
    spdxVersion, name, spdxId, dataLicense, creationInfo, elements, rootElement.

    This normalizer creates a proper @context/@graph structure where the SpdxDocument
    is an element inside the graph.
    """
    elements = data.get("elements", [])

    # Build the SpdxDocument element from root-level fields
    doc_element: dict[str, Any] = {
        "type": "SpdxDocument",
    }
    if "spdxId" in data:
        doc_element["spdxId"] = data["spdxId"]
    if "name" in data:
        doc_element["name"] = data["name"]
    if "dataLicense" in data:
        doc_element["dataLicense"] = data["dataLicense"]
    if "rootElement" in data:
        doc_element["rootElement"] = data["rootElement"]
    if "comment" in data:
        doc_element["comment"] = data["comment"]

    # Promote inline creationInfo dict to a proper CreationInfo graph element.
    # In spec-compliant format, creationInfo is a string reference to a
    # CreationInfo element in @graph. Legacy format has it as an inline dict.
    # Work on a local copy to avoid mutating data["elements"] in-place.
    elements = [dict(e) for e in elements]
    creation_info_id = "_:creationInfo"
    if "creationInfo" in data:
        ci = data["creationInfo"]
        if isinstance(ci, dict):
            ci_element = dict(ci)
            ci_element.setdefault("type", "CreationInfo")
            ci_element.setdefault("@id", creation_info_id)
            elements.insert(0, ci_element)
            doc_element["creationInfo"] = creation_info_id
            # Replace inline creationInfo dicts on elements with the blank node
            # reference so the normalized output uses the shared pattern consistently.
            for elem in elements:
                if isinstance(elem.get("creationInfo"), dict):
                    elem["creationInfo"] = creation_info_id
        else:
            # Already a string reference
            doc_element["creationInfo"] = ci

    # SpdxDocument.element contains the spdxIds of all elements
    doc_element["element"] = [e.get("spdxId", "") for e in elements if e.get("spdxId")]

    # Derive specVersion from the spdxVersion field
    spdx_version = data.get("spdxVersion", "SPDX-3.0.1")
    spec_version = spdx_version.removeprefix("SPDX-")

    graph = list(elements) + [doc_element]

    return {
        "@context": SPDX_30_CONTEXT,
        "@graph": graph,
        # Preserve for downstream access
        "_legacy_spdxVersion": spdx_version,
        "_legacy_specVersion": spec_version,
    }
