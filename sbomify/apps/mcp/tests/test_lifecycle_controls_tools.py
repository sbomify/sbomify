"""Lifecycle (CLE), end-of-life readiness and security controls tools, called for real."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.mcp import registry
from sbomify.apps.mcp.server import build_app

from .test_protocol import mcp_http, parse, structured
from .test_write_tools import call_tool

build_app()

LIFECYCLE_SCOPES = ["product:read", "component:read_internal", "release:read"]
EFFECTIVE = datetime(2027, 1, 1, tzinfo=UTC)


def refusal(response) -> str:
    result = parse(response)["result"]
    assert result.get("isError") is True, result
    return result["content"][0]["text"]


def _scopes(mcp_owner, workspace: str) -> dict[str, Any]:
    """One of each lifecycle scope in the bound or the other workspace, keyed by argument name."""
    from sbomify.apps.core.models import Component, ComponentRelease, Product, Release

    user, bound, other = mcp_owner
    team = bound if workspace == "bound" else other
    product = Product.objects.create(name=f"{workspace} product", team=team)
    component = Component.objects.create(name=f"{workspace} component", team=team)
    return {
        "product_id": product,
        "component_id": component,
        "release_id": Release.objects.create(product=product, name="v1"),
        "component_release_id": ComponentRelease.objects.create(component=component, version="1.0"),
    }


def _seed(scope: str, entity: Any, *, version: str = "1.0", effective: datetime = EFFECTIVE) -> None:
    """An end-of-support event and the support level it names, recorded the way sbomify records them."""
    from sbomify.apps.core.services import cle

    event, definition = {
        "product_id": (cle.create_cle_event, cle.create_support_definition),
        "component_id": (cle.create_component_cle_event, cle.create_component_support_definition),
        "release_id": (cle.create_release_cle_event, cle.create_release_support_definition),
        "component_release_id": (
            cle.create_component_release_cle_event,
            cle.create_component_release_support_definition,
        ),
    }[scope]
    assert definition(entity, "lts", "Long-term support", "https://example.com/lts").ok
    assert event(entity, "endOfSupport", effective, versions=[{"version": version}], support_id="lts").ok


def test_read_only_sees_the_reads_and_no_lifecycle_write_exists():
    """Events are append-only, public over TEA and rewrite a product's dates, so a person records them."""
    read_only = registry.permitted_by(SCOPE_PRESETS["read_only"])
    assert {
        "list_lifecycle_events",
        "list_support_definitions",
        "get_product_eol_readiness",
        "list_control_catalogs",
        "list_controls",
        "get_control",
    } <= read_only
    assert {"create_lifecycle_event", "create_support_definition"} & set(registry.all_specs()) == set()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("scope", ["product_id", "component_id", "release_id", "component_release_id"])
async def test_events_and_definitions_read_on_every_scope(mcp_owner, make_token, scope):
    entities = await sync_to_async(_scopes)(mcp_owner, "bound")
    await sync_to_async(_seed)(scope, entities[scope])
    token = await sync_to_async(make_token)(LIFECYCLE_SCOPES)
    target = {scope: entities[scope].id}

    async with mcp_http() as client:
        listed = await call_tool(client, token, "list_lifecycle_events", target)
        event_id = structured(listed)["items"][0]["event_id"]
        one = await call_tool(client, token, "list_lifecycle_events", {**target, "event_id": event_id})
        definitions = await call_tool(client, token, "list_support_definitions", target)

    assert [row["event_type"] for row in structured(listed)["items"]] == ["endOfSupport"]
    assert structured(listed)["has_more"] is False
    assert structured(one)["versions"] == [{"version": "1.0", "range": None}]
    assert [row["support_id"] for row in structured(definitions)["items"]] == ["lts"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_events_page_and_report_more(make_token, product_in_bound_workspace):
    from sbomify.apps.core.services import cle

    def seed() -> None:
        for version in ("1.0", "1.1", "1.2"):
            created = cle.create_cle_event(product_in_bound_workspace, "released", EFFECTIVE, version=version)
            assert created.ok, created.error

    await sync_to_async(seed)()
    token = await sync_to_async(make_token)(LIFECYCLE_SCOPES)

    async with mcp_http() as client:
        first = await call_tool(
            client, token, "list_lifecycle_events", {"product_id": product_in_bound_workspace.id, "page_size": 2}
        )
        second = await call_tool(
            client,
            token,
            "list_lifecycle_events",
            {"product_id": product_in_bound_workspace.id, "page_size": 2, "page": 2},
        )

    assert [row["version"] for row in structured(first)["items"]] == ["1.2", "1.1"]
    assert structured(first)["has_more"] is True
    assert [row["version"] for row in structured(second)["items"]] == ["1.0"]
    assert structured(second)["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_call_names_exactly_one_scope(make_token, product_in_bound_workspace, component_in_bound_workspace):
    token = await sync_to_async(make_token)(LIFECYCLE_SCOPES)

    async with mcp_http() as client:
        none = await call_tool(client, token, "list_lifecycle_events", {})
        two = await call_tool(
            client,
            token,
            "list_support_definitions",
            {"product_id": product_in_bound_workspace.id, "component_id": component_in_bound_workspace.id},
        )

    assert "exactly one of" in refusal(none)
    assert "exactly one of" in refusal(two)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("scope", ["product_id", "component_id", "release_id", "component_release_id"])
async def test_reads_refuse_another_workspaces_ids(mcp_owner, make_token, scope):
    entities = await sync_to_async(_scopes)(mcp_owner, "other")
    await sync_to_async(_seed)(scope, entities[scope])
    token = await sync_to_async(make_token)(LIFECYCLE_SCOPES)
    target = {scope: entities[scope].id}

    async with mcp_http() as client:
        events = await call_tool(client, token, "list_lifecycle_events", target)
        definitions = await call_tool(client, token, "list_support_definitions", target)

    for response in (events, definitions):
        assert "No " in refusal(response) and "found" in refusal(response)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_eol_readiness(make_token, product_in_bound_workspace, product_in_other_workspace):
    token = await sync_to_async(make_token)(["product:read"])

    async with mcp_http() as client:
        readiness = await call_tool(
            client, token, "get_product_eol_readiness", {"product_id": product_in_bound_workspace.id}
        )
        elsewhere = await call_tool(
            client, token, "get_product_eol_readiness", {"product_id": product_in_other_workspace.id}
        )

    result = structured(readiness)
    assert result["product_id"] == product_in_bound_workspace.id
    assert result["is_ready"] is False
    assert result["problems"]
    assert "No product found" in refusal(elsewhere)


def _catalog(mcp_owner, workspace: str = "bound") -> dict[str, str]:
    from sbomify.apps.controls.models import Control, ControlCatalog, ControlEvidence, ControlMapping, ControlStatus

    _, bound, other = mcp_owner
    team = bound if workspace == "bound" else other
    catalog = ControlCatalog.objects.create(team=team, name=f"{workspace} SOC 2", version="2024")
    access, credentials, monitoring = (
        Control.objects.create(catalog=catalog, group=group, control_id=cid, title=title, sort_order=i)
        for i, (cid, title, group) in enumerate(
            [
                ("CC6.1", "Logical access controls", "Security"),
                ("CC6.2", "Credentials management", "Security"),
                ("CC7.1", "Threat monitoring", "Availability"),
            ]
        )
    )
    status = ControlStatus.objects.create(control=access, status=ControlStatus.Status.COMPLIANT, notes="SSO enforced")
    ControlEvidence.objects.create(
        control_status=status, evidence_type="url", title="SSO policy", url="https://example.com"
    )
    other_catalog = ControlCatalog.objects.create(team=team, name=f"{workspace} ISO", version="2022")
    target = Control.objects.create(catalog=other_catalog, group="A.9", control_id="A.9.1", title="Access policy")
    ControlMapping.objects.create(source_control=access, target_control=target, relation_type="equivalent")
    ControlCatalog.objects.create(team=team, name=f"{workspace} retired", version="1", is_active=False)
    return {"catalog": catalog.id, "access": access.id, "credentials": credentials.id, "monitoring": monitoring.id}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_controls_reads(mcp_owner, make_token):
    from sbomify.apps.controls.models import ControlStatus

    ids = await sync_to_async(_catalog)(mcp_owner)
    token = await sync_to_async(make_token)(["workspace:read"])

    async with mcp_http() as client:
        catalogs = await call_tool(client, token, "list_control_catalogs", {})
        everything = await call_tool(client, token, "list_control_catalogs", {"include_inactive": True})
        compliant = await call_tool(
            client, token, "list_controls", {"catalog_id": ids["catalog"], "status": "compliant"}
        )
        searched = await call_tool(
            client, token, "list_controls", {"catalog_id": ids["catalog"], "search": "security", "page_size": 1}
        )
        detail = await call_tool(client, token, "get_control", {"control_id": ids["access"]})
        bare = await call_tool(client, token, "get_control", {"control_id": ids["monitoring"]})
        bad_status = await call_tool(client, token, "list_controls", {"catalog_id": ids["catalog"], "status": "done"})

    assert {row["name"] for row in structured(catalogs)["catalogs"]} == {"bound SOC 2", "bound ISO"}
    assert len(structured(everything)["catalogs"]) == 3
    assert [row["control_id"] for row in structured(compliant)["items"]] == ["CC6.1"]
    assert structured(searched)["total"] == 2 and structured(searched)["has_more"] is True

    control = structured(detail)
    assert control["status"] == "compliant" and control["notes"] == "SSO enforced"
    assert [row["title"] for row in control["evidence"]["items"]] == ["SSO policy"]
    assert control["mappings"]["items"][0]["target_control_label"] == "A.9.1"
    assert structured(bare)["status"] == "not_implemented"
    assert "Unknown status" in refusal(bad_status)
    # Reading a control with no status must not create one.
    assert not await sync_to_async(ControlStatus.objects.filter(control_id=ids["monitoring"]).exists)()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_controls_reads_refuse_another_workspace(mcp_owner, make_token):
    ids = await sync_to_async(_catalog)(mcp_owner, "other")
    token = await sync_to_async(make_token)(["workspace:read"])

    async with mcp_http() as client:
        catalogs = await call_tool(client, token, "list_control_catalogs", {})
        controls = await call_tool(client, token, "list_controls", {"catalog_id": ids["catalog"]})
        control = await call_tool(client, token, "get_control", {"control_id": ids["access"]})

    assert structured(catalogs)["catalogs"] == []
    assert "No control catalog found" in refusal(controls)
    assert "No control found" in refusal(control)
