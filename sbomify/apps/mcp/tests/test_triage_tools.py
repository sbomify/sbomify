"""The triage loop over MCP: read a vulnerability's prompts, send a ruling for approval, follow it.

Called for real with a token made from the AI agent preset, because that is the
token an unattended agent holds. Nothing here approves anything: deciding is a
person's job in the app, and no tool can reach it.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.mcp import registry
from sbomify.apps.vulnerability_scanning.tests.test_workspace_vulnerabilities import _component, _finding, _scan

from .test_protocol import call, mcp_http, parse, structured

AGENT = SCOPE_PRESETS["agent"]
TRIAGE_TOOLS = {"get_fix_prompt", "submit_vex_for_approval", "list_vex_submissions", "get_vex_submission"}

DECISION = {
    "vuln_id": "CVE-2026-1",
    "purl": "pkg:npm/lodash@4.17.15",
    "state": "not_affected",
    "justification": "code_not_reachable",
    "detail": "The merge helper is never called with user input.",
    "aliases": ["GHSA-aaaa-bbbb-cccc"],
}


def _seed(team):
    component, sbom = _component(team, "api")
    _scan(sbom, [_finding("CVE-2026-1", aliases=["GHSA-aaaa-bbbb-cccc"])])
    return component


async def _call(token, name: str, arguments: dict):
    async with mcp_http() as client:
        return await call(client, "tools/call", token=token.encoded_token, name=name, arguments=arguments)


def _refused(response) -> str:
    payload = parse(response)
    assert payload["result"].get("isError") is True, payload
    return json.dumps(payload)


async def _submit(token, component_id: str):
    return await _call(
        token,
        "submit_vex_for_approval",
        {"component_id": component_id, "decisions": [DECISION], "context": "Checked every caller of merge."},
    )


def test_no_tool_can_decide_a_submission():
    assert all("vex_submission:decide" not in spec.actions for spec in registry.all_specs().values())
    assert "vex_submission:decide" in registry.FORBIDDEN_ACTIONS


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_agent_token_sees_the_triage_tools_and_no_upload(make_token):
    token = await sync_to_async(make_token)(AGENT)
    async with mcp_http() as client:
        response = await call(client, "tools/list", token=token.encoded_token)

    names = {tool["name"] for tool in parse(response)["result"]["tools"]}
    assert TRIAGE_TOOLS | {"list_vulnerabilities"} <= names
    assert "upload_vex" not in names
    assert "upload_artifact" not in names


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_list_vulnerabilities_names_the_purl_the_prompt_needs(make_token, mcp_owner):
    _, bound, _ = mcp_owner
    component = await sync_to_async(_seed)(bound)
    token = await sync_to_async(make_token)(AGENT)

    rows = structured(await _call(token, "list_vulnerabilities", {"component_id": component.id}))["items"]

    assert [(row["id"], row["purl"]) for row in rows] == [("CVE-2026-1", "pkg:npm/lodash@4.17.15")]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_fix_prompt_returns_both_prompts(make_token, mcp_owner):
    _, bound, _ = mcp_owner
    component = await sync_to_async(_seed)(bound)
    token = await sync_to_async(make_token)(AGENT)

    result = structured(
        await _call(
            token,
            "get_fix_prompt",
            {"component_id": component.id, "advisory": "CVE-2026-1", "purl": "pkg:npm/lodash@4.17.15"},
        )
    )

    assert result["advisory"] == "CVE-2026-1"
    assert result["purl"] == "pkg:npm/lodash@4.17.15"
    assert "Triage CVE-2026-1 in lodash" in result["triage_prompt"]
    assert "Fix CVE-2026-1 in lodash" in result["fix_prompt"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_submission_waits_for_a_person_and_reads_as_the_agents(make_token, mcp_owner):
    from sbomify.apps.vulnerability_scanning.models import VexSubmission

    _, bound, _ = mcp_owner
    component = await sync_to_async(_seed)(bound)
    token = await sync_to_async(make_token)(AGENT)

    submitted = structured(await _submit(token, component.id))

    assert submitted["status"] == "pending"
    assert submitted["source"] == "agent"
    stored = await sync_to_async(VexSubmission.objects.get)(pk=submitted["id"])
    assert stored.status == VexSubmission.Status.PENDING

    fetched = structured(await _call(token, "get_vex_submission", {"submission_id": submitted["id"]}))
    assert fetched["status"] == "pending"
    listed = structured(await _call(token, "list_vex_submissions", {"status": "pending"}))
    assert [item["id"] for item in listed["items"]] == [submitted["id"]]
    by_component = structured(await _call(token, "list_vex_submissions", {"component_id": component.id}))
    assert [item["id"] for item in by_component["items"]] == [submitted["id"]]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_read_only_token_cannot_submit(make_token, mcp_owner):
    _, bound, _ = mcp_owner
    component = await sync_to_async(_seed)(bound)
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    assert "Not permitted" in _refused(await _submit(token, component.id))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_another_workspaces_component_is_refused(make_token, mcp_owner):
    from sbomify.apps.vulnerability_scanning.models import VexSubmission

    _, _, other = mcp_owner
    component = await sync_to_async(_seed)(other)
    token = await sync_to_async(make_token)(AGENT)

    _refused(await _submit(token, component.id))
    _refused(await _call(token, "get_fix_prompt", {"component_id": component.id, "advisory": "CVE-2026-1"}))
    assert not await sync_to_async(VexSubmission.objects.exists)()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_another_workspaces_submission_is_not_found(make_token, mcp_owner):
    _, _, other = mcp_owner
    component = await sync_to_async(_seed)(other)
    other_token = await sync_to_async(make_token)(AGENT, other)
    submitted = structured(await _submit(other_token, component.id))
    token = await sync_to_async(make_token)(AGENT)

    assert "not found" in _refused(await _call(token, "get_vex_submission", {"submission_id": submitted["id"]})).lower()
    listed = structured(await _call(token, "list_vex_submissions", {}))
    assert listed["items"] == []
