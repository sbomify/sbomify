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
