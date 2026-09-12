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


def _artifact(component, name: str, bom_type: str, version: str = "1.0.0") -> SBOM:
    return SBOM.objects.create(
        name=name,
        version=version,
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


def test_a_blank_search_is_not_a_filter():
    """An agent passing "" means "no search", not "match the empty string".

    Treating it as a filter would still match everything today, but the two
    readings diverge the moment the helper is used with anything but icontains.
    """
    from sbomify.apps.core.models import Product
    from sbomify.apps.mcp.tools._base import narrow

    base = Product.objects.all()

    assert narrow(base, None, "name").query.where is base.query.where
    assert str(narrow(base, "   ", "name").query) == str(base.query)
    assert str(narrow(base, "widget", "name").query) != str(base.query)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_search_narrows_instead_of_making_the_agent_page(mcp_owner, make_token, component_in_bound_workspace):
    """Listing everything and letting the agent read past it spends the scarce
    resource, which is context rather than queries."""
    await sync_to_async(_artifact)(component_in_bound_workspace, "widget-firmware", SBOM.BomType.SBOM, "1.0.0")
    await sync_to_async(_artifact)(component_in_bound_workspace, "gateway-image", SBOM.BomType.SBOM, "2.0.0")
    token = await sync_to_async(make_token)(["sbom:read"])

    hit = structured(
        await _call(token, "list_artifacts", component_id=component_in_bound_workspace.id, search="WIDGET")
    )
    everything = structured(await _call(token, "list_artifacts", component_id=component_in_bound_workspace.id))

    assert [row["name"] for row in hit["items"]] == ["widget-firmware"], "search should be case-insensitive"
    assert hit["total"] == 1
    assert everything["total"] == 2


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_concise_packages_drop_what_a_yes_or_no_question_does_not_need(
    mcp_owner, make_token, component_in_bound_workspace, monkeypatch
):
    from sbomify.apps.core import object_store

    artifact = await sync_to_async(_artifact)(component_in_bound_workspace, "img", SBOM.BomType.SBOM)
    document = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [
                {
                    "type": "library",
                    "name": "libexample",
                    "version": "1.0.0",
                    "purl": "pkg:pypi/libexample@1.0.0",
                    "licenses": [{"license": {"id": "MIT"}}],
                }
            ],
        }
    ).encode()
    monkeypatch.setattr(object_store.StorageClient, "get_sbom_data", lambda self, name: document)
    token = await sync_to_async(make_token)(["sbom:read"])

    detailed = structured(await _call(token, "get_artifact_packages", artifact_id=artifact.id))
    concise = structured(
        await _call(token, "get_artifact_packages", artifact_id=artifact.id, response_format="concise")
    )

    assert set(detailed["items"][0]) >= {"name", "version", "purl", "licenses"}
    assert set(concise["items"][0]) == {"name", "version"}
    assert concise["total"] == detailed["total"], "verbosity must not change what matched"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_the_risk_report_counts_every_bom_kind_the_release_ships(
    mcp_owner, make_token, component_in_bound_workspace, product_in_bound_workspace
):
    """`get_release_risk_report` is the one-call answer, so its counts must be whole.

    Scanning only ever covers `bom_type=sbom`, and the count of what the
    release ships was reusing that filtered list. A release carrying a CBOM and
    a VEX alongside its SBOM reported one artifact, and the tool's own
    docstring tells the agent to prefer it over calling `get_release`.
    """
    from sbomify.apps.core.models import Release, ReleaseArtifact

    def setup() -> str:
        release = Release.objects.create(product=product_in_bound_workspace, name="v1", version="1")
        for index, bom_type in enumerate((SBOM.BomType.SBOM, SBOM.BomType.CBOM, SBOM.BomType.VEX)):
            artifact = _artifact(component_in_bound_workspace, f"the-{bom_type}", bom_type, version=f"1.0.{index}")
            ReleaseArtifact.objects.create(release=release, sbom=artifact)
        return release.id

    release_id = await sync_to_async(setup)()
    token = await sync_to_async(make_token)(["release:read", "workspace:read"])

    report = structured(await _call(token, "get_release_risk_report", release_id=release_id))

    assert report["artifact_counts"]["boms"] == 3
    # The scan fields stay SBOM-only: a VEX or CBOM row can never earn a
    # security run, so counting one would report it forever unscanned.
    assert report["unscanned_sboms"] == 1


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_detail_tool_cuts_its_collections_rather_than_tripping_the_cap(
    mcp_owner, make_token, product_in_bound_workspace
):
    """A detail tool takes no page argument, so an unbounded collection was a dead end.

    Over the response cap, `enforce_response_size` tells the agent to narrow
    the query with an argument `get_product` does not have. Cutting the list
    and saying so leaves it an answer plus somewhere to go for the rest.
    """
    from sbomify.apps.core.models import Component
    from sbomify.apps.mcp.tools._base import DETAIL_COLLECTION_LIMIT

    _, bound, _ = mcp_owner

    def setup() -> None:
        for i in range(DETAIL_COLLECTION_LIMIT + 5):
            component = Component.objects.create(name=f"component-{i:03d}", team=bound)
            product_in_bound_workspace.components.add(component)

    await sync_to_async(setup)()
    token = await sync_to_async(make_token)(["product:read"])

    detail = structured(await _call(token, "get_product", product_id=product_in_bound_workspace.id))

    components = detail["components"]
    assert len(components["items"]) == DETAIL_COLLECTION_LIMIT
    assert components["total"] == DETAIL_COLLECTION_LIMIT + 5
    assert components["truncated"] is True
    assert product_in_bound_workspace.id in components["more_with"], "name the tool that can page the rest"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_small_product_is_not_marked_truncated(mcp_owner, make_token, product_in_bound_workspace):
    """The flag has to mean something, so it must be absent on a normal answer."""
    from sbomify.apps.core.models import Component

    _, bound, _ = mcp_owner

    def setup() -> None:
        product_in_bound_workspace.components.add(Component.objects.create(name="only-one", team=bound))

    await sync_to_async(setup)()
    token = await sync_to_async(make_token)(["product:read"])

    detail = structured(await _call(token, "get_product", product_id=product_in_bound_workspace.id))

    assert detail["components"]["total"] == 1
    assert "truncated" not in detail["components"]
    assert "more_with" not in detail["components"]
