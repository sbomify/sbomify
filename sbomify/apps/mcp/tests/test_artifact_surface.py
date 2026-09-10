"""The artifact tools reach every kind an artifact can be.

The BOM table holds eight ``bom_type`` values and documents live in a second
table, so "list the artifacts" is two tools and one filter. These pin that an
agent can name a kind and get only that kind back, and that the document half
has a detail read at all.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.sboms.models import SBOM

from .test_protocol import call, mcp_http, parse, structured


def _artifact(component, name: str, bom_type: str) -> SBOM:
    return SBOM.objects.create(
        name=name,
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename=f"{name}.json",
        component=component,
        bom_type=bom_type,
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_artifacts_narrows_to_one_bom_type(mcp_owner, make_token, component_in_bound_workspace):
    await sync_to_async(_artifact)(component_in_bound_workspace, "the-sbom", SBOM.BomType.SBOM)
    await sync_to_async(_artifact)(component_in_bound_workspace, "the-cbom", SBOM.BomType.CBOM)
    token = await sync_to_async(make_token)(["sbom:read"])

    async with mcp_http() as client:
        both = structured(
            await call(
                client,
                "tools/call",
                token=token.encoded_token,
                name="list_artifacts",
                arguments={"component_id": component_in_bound_workspace.id},
            )
        )
        only_cbom = structured(
            await call(
                client,
                "tools/call",
                token=token.encoded_token,
                name="list_artifacts",
                arguments={"component_id": component_in_bound_workspace.id, "bom_type": "cbom"},
            )
        )

    assert {"the-sbom", "the-cbom"} <= {row["name"] for row in both["items"]}
    assert [row["name"] for row in only_cbom["items"]] == ["the-cbom"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_unknown_bom_type_is_named_not_ignored(mcp_owner, make_token, component_in_bound_workspace):
    """Silently returning every kind would have the agent report the wrong answer."""
    token = await sync_to_async(make_token)(["sbom:read"])

    async with mcp_http() as client:
        response = await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="list_artifacts",
            arguments={"component_id": component_in_bound_workspace.id, "bom_type": "nonsense"},
        )

    body = json.dumps(parse(response))
    assert "Unknown bom_type" in body
    assert "cbom" in body, "the message should list what is valid"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("bom_type", [choice for choice in SBOM.BomType.values])
async def test_every_bom_type_is_readable_end_to_end(
    mcp_owner, make_token, component_in_bound_workspace, monkeypatch, bom_type
):
    """Each of the eight kinds must survive list, detail and package read.

    The kinds are one table and one code path, so a regression here would show
    up on whichever kind the fixture happened to use. Running all of them means
    a CBOM cannot quietly stop parsing while SBOMs keep working.
    """
    from sbomify.apps.core import object_store

    artifact = await sync_to_async(_artifact)(component_in_bound_workspace, f"the-{bom_type}", bom_type)
    document = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"type": "library", "name": "libexample", "version": "1.0.0"}],
        }
    ).encode()
    monkeypatch.setattr(object_store.StorageClient, "get_sbom_data", lambda self, name: document, raising=False)
    token = await sync_to_async(make_token)(["sbom:read"])

    listed = structured(
        await _call(token, "list_artifacts", component_id=component_in_bound_workspace.id, bom_type=bom_type)
    )
    detail = structured(await _call(token, "get_artifact", artifact_id=artifact.id))
    packages = structured(await _call(token, "get_artifact_packages", artifact_id=artifact.id))

    assert [row["bom_type"] for row in listed["items"]] == [bom_type]
    assert detail["bom_type"] == bom_type
    assert [pkg["name"] for pkg in packages["items"]] == ["libexample"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_document_is_reachable_in_both_directions(mcp_owner, make_token, component_in_bound_workspace):
    """The document half of the artifact surface: listed, then read in detail."""
    from sbomify.apps.documents.models import Document

    doc = await sync_to_async(Document.objects.create)(
        name="threat-model",
        version="1.0",
        component=component_in_bound_workspace,
        document_filename="threat-model.pdf",
    )
    token = await sync_to_async(make_token)(["document:read"])

    listed = structured(await _call(token, "list_documents", component_id=component_in_bound_workspace.id))
    detail = structured(await _call(token, "get_document", document_id=doc.id))

    assert [row["name"] for row in listed["items"]] == ["threat-model"]
    assert detail["id"] == doc.id
    assert detail["filename"] == "threat-model.pdf"


async def _call(token, name, **arguments):
    async with mcp_http() as client:
        return await call(client, "tools/call", token=token.encoded_token, name=name, arguments=arguments)
