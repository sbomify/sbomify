"""A conformant SPDX 3.0.1 fixture corpus.

Every earlier SPDX 3 fixture in this suite encoded the non-spec spellings
(``externalIdentifiers``, ``packageURL``), so the suite stayed green while a
spec-conformant document scored worse than a malformed one. These builders
write the spellings the spec defines, and the corpus test validates each
document against the vendored ``spdx_3.0.1-schema.json`` so the fixtures
cannot drift from the spec again.

Builders return fresh dicts — tests may mutate freely.
"""

from __future__ import annotations

from typing import Any

CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"
CREATED = "2026-08-01T00:00:00Z"

_CI = "_:creationinfo"


def _creation_info(created_by: list[Any] | None = None, created_using: list[Any] | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "type": "CreationInfo",
        "@id": _CI,
        "specVersion": "3.0.1",
        "created": CREATED,
        "createdBy": created_by if created_by is not None else ["urn:acme:agent"],
    }
    if created_using is not None:
        info["createdUsing"] = created_using
    return info


def _person(spdx_id: str = "urn:acme:agent", name: str = "Jane Doe", email: str = "jane@acme.test") -> dict[str, Any]:
    return {
        "type": "Person",
        "spdxId": spdx_id,
        "creationInfo": _CI,
        "name": name,
        "externalIdentifier": [{"type": "ExternalIdentifier", "externalIdentifierType": "email", "identifier": email}],
    }


def _tool(spdx_id: str = "urn:acme:tool", name: str = "sbomify-action-1.2.3") -> dict[str, Any]:
    return {"type": "Tool", "spdxId": spdx_id, "creationInfo": _CI, "name": name}


def _document(root: list[str] | str, spdx_id: str = "urn:acme:doc") -> dict[str, Any]:
    return {
        "type": "SpdxDocument",
        "spdxId": spdx_id,
        "creationInfo": _CI,
        "rootElement": root,
        "profileConformance": ["core", "software"],
    }


def _package(
    spdx_id: str = "urn:acme:pkg1",
    name: str = "my-app",
    version: str = "1.2.3",
    supplier: Any = "urn:acme:agent",
    **extra: Any,
) -> dict[str, Any]:
    package: dict[str, Any] = {
        "type": "software_Package",
        "spdxId": spdx_id,
        "creationInfo": _CI,
        "name": name,
        "software_packageVersion": version,
        "software_downloadLocation": f"https://downloads.acme.test/{name}-{version}.tar.gz",
        "verifiedUsing": [{"type": "Hash", "algorithm": "sha256", "hashValue": "a" * 64}],
        "externalRef": [
            {"type": "ExternalRef", "externalRefType": "vcs", "locator": [f"https://github.com/acme/{name}"]}
        ],
        "validUntilTime": "2030-01-01T00:00:00Z",
    }
    if supplier is not None:
        package["originatedBy"] = [supplier]
    package.update(extra)
    return package


def _relationship(rel_type: str, from_id: str, to_ids: list[str], spdx_id: str = "urn:acme:rel1") -> dict[str, Any]:
    return {
        "type": "Relationship",
        "spdxId": spdx_id,
        "creationInfo": _CI,
        "relationshipType": rel_type,
        "from": from_id,
        "to": to_ids,
    }


def _doc(*graph: dict[str, Any]) -> dict[str, Any]:
    return {"@context": CONTEXT, "@graph": list(graph)}


def minimal_conformant() -> dict[str, Any]:
    """One package carrying every field the four plugins grade, spec-spelled."""
    return _doc(
        _creation_info(created_using=["urn:acme:tool"]),
        _person(),
        _tool(),
        _document(["urn:acme:pkg1"]),
        _package(software_packageUrl="pkg:pypi/my-app@1.2.3"),
        _relationship("hasConcludedLicense", "urn:acme:pkg1", ["urn:acme:lic1"]),
        _relationship("hasDeclaredLicense", "urn:acme:pkg1", ["urn:acme:lic1"], spdx_id="urn:acme:rel2"),
    )


def root_element_non_first() -> dict[str, Any]:
    """Three packages; the SpdxDocument declares the third as the subject."""
    return _doc(
        _creation_info(),
        _person(),
        _document(["urn:acme:pkg3"]),
        _package("urn:acme:pkg1", name="libfoo", version="9.9.9"),
        _package("urn:acme:pkg2", name="libbar", version="2.0.0"),
        _package("urn:acme:pkg3", name="my-app", version="1.2.3", software_packageUrl="pkg:pypi/my-app@1.2.3"),
    )


def inline_agents() -> dict[str, Any]:
    """Inline Agent objects in createdBy and originatedBy — legal per
    Agent_derived, and the shape that crashed two plugins."""
    inline_org = {
        "type": "Organization",
        "spdxId": "urn:acme:inlineorg",
        "creationInfo": _CI,
        "name": "Inline Corp",
        "externalIdentifier": [
            {"type": "ExternalIdentifier", "externalIdentifierType": "email", "identifier": "sec@inline.test"}
        ],
    }
    return _doc(
        _creation_info(created_by=[dict(inline_org)]),
        _document(["urn:acme:pkg1"]),
        _package(supplier=dict(inline_org), software_packageUrl="pkg:pypi/my-app@1.2.3"),
    )


def software_agent_supplier() -> dict[str, Any]:
    """Supplier typed SoftwareAgent — routed to the wrong bucket before."""
    agent = {
        "type": "SoftwareAgent",
        "spdxId": "urn:acme:bot",
        "creationInfo": _CI,
        "name": "build-bot",
        "externalIdentifier": [
            {"type": "ExternalIdentifier", "externalIdentifierType": "email", "identifier": "bot@acme.test"}
        ],
    }
    return _doc(
        _creation_info(created_by=["urn:acme:bot"]),
        agent,
        _document(["urn:acme:pkg1"]),
        _package(supplier="urn:acme:bot", software_packageUrl="pkg:pypi/my-app@1.2.3"),
    )


def purl_via_software_package_url_only() -> dict[str, Any]:
    """The first-class 3.0.1 purl property, and nothing else."""
    return _doc(
        _creation_info(),
        _person(),
        _document(["urn:acme:pkg1"]),
        _package(software_packageUrl="pkg:pypi/my-app@1.2.3"),
    )


def purl_via_external_identifier_only() -> dict[str, Any]:
    """Spec spelling: singular property, packageUrl vocabulary value."""
    return _doc(
        _creation_info(),
        _person(),
        _document(["urn:acme:pkg1"]),
        _package(
            externalIdentifier=[
                {
                    "type": "ExternalIdentifier",
                    "externalIdentifierType": "packageUrl",
                    "identifier": "pkg:pypi/my-app@1.2.3",
                }
            ]
        ),
    )


def legacy_spelling_counterpart() -> dict[str, Any]:
    """The same package data as purl_via_external_identifier_only, written
    with the non-spec spellings stored artifacts carry. Deliberately NOT
    schema-valid — the A/B guard proves it scores no better than the
    conformant twin."""
    document = purl_via_external_identifier_only()
    for element in document["@graph"]:
        if element["type"] == "software_Package":
            element["externalIdentifiers"] = [
                {"externalIdentifierType": "packageURL", "identifier": "pkg:pypi/my-app@1.2.3"}
            ]
            del element["externalIdentifier"]
        if element["type"] == "Person":
            element["externalIdentifiers"] = element.pop("externalIdentifier")
    return document


def yocto_shaped() -> dict[str, Any]:
    """The shape current Yocto (5.2+/6.0) emits: 3.0.1, purls via
    software_packageUrl, one de-duplicated CreationInfo shared by reference."""
    return _doc(
        _creation_info(created_by=["urn:oe:org"]),
        {"type": "Organization", "spdxId": "urn:oe:org", "creationInfo": _CI, "name": "OpenEmbedded"},
        _document(["urn:oe:sbom"]),
        {
            "type": "software_Sbom",
            "spdxId": "urn:oe:sbom",
            "creationInfo": _CI,
            "software_sbomType": ["build"],
            "rootElement": ["urn:oe:image"],
            "element": ["urn:oe:image", "urn:oe:netbase"],
        },
        _package(
            "urn:oe:image",
            name="core-image-minimal",
            version="6.0",
            supplier="urn:oe:org",
            software_packageUrl="pkg:generic/core-image-minimal@6.0",
        ),
        _package(
            "urn:oe:netbase",
            name="netbase",
            version="6.4",
            supplier="urn:oe:org",
            software_packageUrl="pkg:generic/netbase@6.4?distro=yocto",
        ),
    )


def syft_shaped() -> dict[str, Any]:
    """The shape syft v1.46+ writes: SPDX 3.0 converted from its 2.3 model,
    describes relationship rather than rootElement, purl on externalIdentifier."""
    document = _doc(
        _creation_info(created_using=["urn:syft:tool"]),
        _person("urn:syft:agent", name="Anchore", email="oss@anchore.test"),
        _tool("urn:syft:tool", name="syft-1.46.0"),
        {
            "type": "SpdxDocument",
            "spdxId": "urn:syft:doc",
            "creationInfo": _CI,
            "profileConformance": ["core", "software"],
        },
        _package(
            "urn:syft:pkg1",
            name="left-pad",
            version="1.3.0",
            supplier="urn:syft:agent",
            externalIdentifier=[
                {
                    "type": "ExternalIdentifier",
                    "externalIdentifierType": "packageUrl",
                    "identifier": "pkg:npm/left-pad@1.3.0",
                }
            ],
        ),
        _relationship("describes", "urn:syft:doc", ["urn:syft:pkg1"], spdx_id="urn:syft:rel1"),
    )
    document["@context"] = "https://spdx.org/rdf/3.0.0/spdx-context.jsonld"
    for element in document["@graph"]:
        if element["type"] == "CreationInfo":
            element["specVersion"] = "3.0.0"
    return document


def spdx_3_0_0() -> dict[str, Any]:
    """A 3.0.0 document — inside SPDX 3 detection, below the BSI floor."""
    document = minimal_conformant()
    document["@context"] = "https://spdx.org/rdf/3.0.0/spdx-context.jsonld"
    for element in document["@graph"]:
        if element["type"] == "CreationInfo":
            element["specVersion"] = "3.0.0"
    return document


def spdx_3_1() -> dict[str, Any]:
    """A 3.1 document — prerelease, to be rejected with a clear error."""
    document = minimal_conformant()
    document["@context"] = "https://spdx.org/rdf/3.1.0/spdx-context.jsonld"
    for element in document["@graph"]:
        if element["type"] == "CreationInfo":
            element["specVersion"] = "3.1.0"
    return document


SCHEMA_VALID_BUILDERS = [
    minimal_conformant,
    root_element_non_first,
    inline_agents,
    software_agent_supplier,
    purl_via_software_package_url_only,
    purl_via_external_identifier_only,
    yocto_shaped,
]
