"""The vulnerability insight tools and the supplier tools, called for real."""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async

from .test_protocol import call, mcp_http, parse, structured
from .test_write_tools import call_tool

CRITICAL_FINDING = {
    "summary": {"total_findings": 1, "by_severity": {"critical": 1}},
    "findings": [
        {
            "id": "CVE-2025-11111",
            "severity": "critical",
            "cvss_score": 9.8,
            "component": {"name": "libexample", "version": "1.0.0", "purl": "pkg:pypi/libexample@1.0.0"},
        }
    ],
}

NOT_AFFECTED_VEX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.6",
    "version": 1,
    "vulnerabilities": [
        {
            "id": "CVE-2025-11111",
            "analysis": {"state": "not_affected", "justification": "code_not_reachable"},
            "affects": [{"ref": "pkg:pypi/libexample@1.0.0"}],
        }
    ],
}


def _scanned_sbom(component):
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.sboms.models import SBOM

    sbom = SBOM.objects.create(
        name="insights",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="insights.json",
        component=component,
    )
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0.0",
        plugin_config_hash="",
        category="security",
        run_reason="on_upload",
        status="completed",
        result=CRITICAL_FINDING,
    )
    return sbom


def _error(response) -> str:
    payload = parse(response)
    assert payload["result"].get("isError") is True, payload
    return json.dumps(payload)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_kpis_come_from_the_workspace_and_clamp_the_window(make_token):
    token = await sync_to_async(make_token)(["workspace:read"])

    async with mcp_http() as client:
        default = structured(await call_tool(client, token, "get_vulnerability_kpis", {}))
        short = structured(await call_tool(client, token, "get_vulnerability_kpis", {"days": 1}))

    assert default["days"] == 90
    assert default["open_critical"] == 0
    assert short["days"] == 7


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_trends_count_a_completed_scan(make_token, component_in_bound_workspace):
    await sync_to_async(_scanned_sbom)(component_in_bound_workspace)
    token = await sync_to_async(make_token)(["workspace:read"])

    async with mcp_http() as client:
        trends = structured(
            await call_tool(
                client,
                token,
                "get_vulnerability_trends",
                {"days": 30, "granularity": "day", "component_id": component_in_bound_workspace.id},
            )
        )
        bad = await call_tool(client, token, "get_vulnerability_trends", {"granularity": "hour"})

    assert trends["summary"]["total_scans"] == 1
    assert trends["time_series"][0]["avg_critical_vulnerabilities"] == 1.0
    assert "Unknown granularity" in _error(bad)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_trends_refuse_a_component_from_another_workspace(make_token, component_in_other_workspace):
    token = await sync_to_async(make_token)(["workspace:read"])

    async with mcp_http() as client:
        response = await call_tool(
            client, token, "get_vulnerability_trends", {"component_id": component_in_other_workspace.id}
        )

    assert "No component found" in _error(response)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_component_triage_pages_the_recorded_decisions(make_token, component_in_bound_workspace, monkeypatch):
    from sbomify.apps.vulnerability_scanning import triage

    index = {
        ("cve-2", "pkg:pypi/b@1"): {"id": "CVE-2", "state": "not_affected", "detail": "x" * 5000},
        ("cve-1", "pkg:pypi/a@1"): {"id": "CVE-1", "state": "exploitable", "detail": "patched in 2"},
    }
    monkeypatch.setattr(triage, "current_triage_index", lambda component: index)
    token = await sync_to_async(make_token)(["component:access"])

    async with mcp_http() as client:
        first = structured(
            await call_tool(
                client, token, "get_component_triage", {"component_id": component_in_bound_workspace.id, "page_size": 1}
            )
        )
        second = structured(
            await call_tool(
                client,
                token,
                "get_component_triage",
                {"component_id": component_in_bound_workspace.id, "page_size": 1, "page": 2},
            )
        )

    assert first["total"] == 2
    assert first["items"][0]["vuln_id"] == "CVE-1"
    assert second["items"][0]["vuln_id"] == "CVE-2"
    assert len(second["items"][0]["detail"]) < 5000
    assert "not_affected" in first["states"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_component_triage_refuses_a_component_from_another_workspace(make_token, component_in_other_workspace):
    token = await sync_to_async(make_token)(["component:access"])

    async with mcp_http() as client:
        response = await call_tool(
            client, token, "get_component_triage", {"component_id": component_in_other_workspace.id}
        )

    assert "No component found" in _error(response)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_preview_vex_counts_what_it_would_suppress_and_stores_nothing(make_token, component_in_bound_workspace):
    from sbomify.apps.sboms.models import SBOM

    await sync_to_async(_scanned_sbom)(component_in_bound_workspace)
    token = await sync_to_async(make_token)(["component:access"])

    async with mcp_http() as client:
        preview = structured(
            await call_tool(
                client,
                token,
                "preview_vex",
                {"component_id": component_in_bound_workspace.id, "content": json.dumps(NOT_AFFECTED_VEX)},
            )
        )
        not_vex = await call_tool(
            client, token, "preview_vex", {"component_id": component_in_bound_workspace.id, "content": "not json"}
        )

    assert preview["format"] == "cyclonedx"
    assert preview["would_suppress"] == 1
    assert await sync_to_async(SBOM.objects.filter(bom_type=SBOM.BomType.VEX).count)() == 0
    assert "VEX preview failed" in _error(not_vex)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_preview_vex_refuses_a_document_too_costly_to_parse(make_token, component_in_bound_workspace, monkeypatch):
    """Under the upload cap is not enough: a document of many small values takes far more memory parsed."""
    from sbomify.apps.mcp import limits

    monkeypatch.setattr(limits, "MAX_ARTIFACT_PARSE_BYTES", 4096)
    many_small_values = json.dumps({"bomFormat": "CycloneDX", "vulnerabilities": [0] * 1000})
    assert len(many_small_values) < 4096
    token = await sync_to_async(make_token)(["component:access"])

    async with mcp_http() as client:
        refused = await call_tool(
            client, token, "preview_vex", {"component_id": component_in_bound_workspace.id, "content": many_small_values}
        )

    assert "too many small parts" in _error(refused)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_suppliers_are_created_listed_and_updated(make_token):
    from sbomify.apps.teams.models import Supplier

    token = await sync_to_async(make_token)(["workspace:read", "workspace:manage"])

    async with mcp_http() as client:
        created = structured(
            await call_tool(client, token, "create_supplier", {"name": "Acme", "contact_email": "sec@acme.example"})
        )
        duplicate = await call_tool(client, token, "create_supplier", {"name": "ACME"})
        updated = structured(
            await call_tool(
                client, token, "update_supplier", {"supplier_id": created["id"], "website": "https://a.example"}
            )
        )
        listed = structured(await call_tool(client, token, "list_suppliers", {"search": "acme"}))
        empty = await call_tool(client, token, "update_supplier", {"supplier_id": created["id"]})

    row = await sync_to_async(Supplier.objects.get)(pk=created["id"])
    assert row.contact_email == "sec@acme.example"
    assert row.website == "https://a.example"
    assert updated["website"] == "https://a.example"
    assert [item["id"] for item in listed["items"]] == [created["id"]]
    assert "already exists" in _error(duplicate)
    assert "Nothing to update" in _error(empty)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_supplier_refuses_one_from_another_workspace(mcp_owner, make_token):
    from sbomify.apps.teams.models import Supplier

    _, _, other = mcp_owner
    elsewhere = await sync_to_async(Supplier.objects.create)(team=other, name="Elsewhere")
    token = await sync_to_async(make_token)(["workspace:read", "workspace:manage"])

    async with mcp_http() as client:
        response = await call_tool(client, token, "update_supplier", {"supplier_id": elsewhere.id, "name": "Taken"})

    assert "No supplier found" in _error(response)
    refreshed = await sync_to_async(Supplier.objects.get)(pk=elsewhere.id)
    assert refreshed.name == "Elsewhere"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_read_token_sees_the_reads_but_not_the_writes_or_component_tools(make_token):
    token = await sync_to_async(make_token)(["workspace:read"])

    async with mcp_http() as client:
        response = await call(client, "tools/list", token=token.encoded_token)

    names = {tool["name"] for tool in parse(response)["result"]["tools"]}
    assert {"get_vulnerability_kpis", "get_vulnerability_trends", "list_suppliers"} <= names
    assert not names & {"create_supplier", "update_supplier", "get_component_triage", "preview_vex"}
