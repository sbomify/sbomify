"""The advisory edit tools write a draft at once and hold a published advisory for a person.

An AI agent token's change to a published advisory becomes a proposal, through
the REST view. Any other token would change what the trust center shows with
nobody reading it first, so the tools refuse it.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.security_advisories.models import AdvisoryProductStatus, AdvisoryProposal, SecurityAdvisory

from .test_advisories import _advisory, _tool
from .test_protocol import parse, structured

AGENT = SCOPE_PRESETS["agent"]


async def _title(advisory: SecurityAdvisory) -> str:
    return (await SecurityAdvisory.objects.aget(pk=advisory.pk)).title


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_agent_edits_its_draft_at_once(mcp_owner, make_token):
    _, bound, _ = mcp_owner
    draft = await sync_to_async(_advisory)(bound, "Heap overflow", status=SecurityAdvisory.Status.DRAFT)
    token = await sync_to_async(make_token)(AGENT)

    payload = structured(
        await _tool(token, "update_advisory", advisory_id=draft.id, changes={"title": "Heap overflow in libexample"})
    )

    assert payload["held_for_approval"] is False
    assert payload["advisory"]["title"] == "Heap overflow in libexample"
    assert await _title(draft) == "Heap overflow in libexample"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_agent_change_to_a_published_advisory_waits_for_a_person(mcp_owner, make_token):
    _, bound, _ = mcp_owner
    published = await sync_to_async(_advisory)(bound, "Heap overflow", status=SecurityAdvisory.Status.PUBLISHED)
    token = await sync_to_async(make_token)(AGENT)

    edit = structured(
        await _tool(
            token,
            "update_advisory",
            advisory_id=published.id,
            changes={"title": "Heap overflow in libexample"},
            context="The upstream advisory names the library.",
        )
    )
    note = structured(
        await _tool(token, "post_advisory_update", advisory_id=published.id, kind="update", note="Fix is in review.")
    )

    assert edit["held_for_approval"] is True
    assert edit["proposal"]["kind"] == "edit_advisory"
    assert edit["proposal"]["status"] == "pending"
    assert note["proposal"]["kind"] == "post_update"
    assert await _title(published) == "Heap overflow", "nothing reaches the trust center until a person approves"

    sent = structured(await _tool(token, "list_advisory_proposals", status="pending"))
    assert {row["id"] for row in sent["items"]} == {edit["proposal"]["id"], note["proposal"]["id"]}
    assert all(row["advisory_id"] == published.id for row in sent["items"])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_another_token_cannot_change_a_published_advisory(mcp_owner, make_token):
    _, bound, _ = mcp_owner
    published = await sync_to_async(_advisory)(bound, "Heap overflow", status=SecurityAdvisory.Status.PUBLISHED)
    token = await sync_to_async(make_token)(None)

    body = json.dumps(
        parse(await _tool(token, "update_advisory", advisory_id=published.id, changes={"title": "Rewritten"}))
    )

    assert "AI agent preset" in body
    assert await _title(published) == "Heap overflow"
    assert not await AdvisoryProposal.objects.filter(advisory_id=published.id).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_agent_names_a_product_on_its_draft_and_rules_on_it(
    mcp_owner, make_token, product_in_bound_workspace
):
    token = await sync_to_async(make_token)(AGENT)
    draft = structured(await _tool(token, "create_advisory", title="Heap overflow", identifier="CVE-2026-0001"))

    added = structured(
        await _tool(token, "add_advisory_product", advisory_id=draft["id"], product_id=product_in_bound_workspace.id)
    )
    ruled = structured(
        await _tool(
            token,
            "set_advisory_product_status",
            advisory_id=draft["id"],
            product_id=product_in_bound_workspace.id,
            change={"status": "not_affected", "justification": "code_not_present"},
        )
    )

    assert added["held_for_approval"] is False
    assert ruled["held_for_approval"] is False
    statuses = AdvisoryProductStatus.objects.filter(
        vulnerability__advisory_id=draft["id"], advisory_product__product=product_in_bound_workspace
    )
    assert [row.status async for row in statuses] == ["not_affected"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_since_that_is_not_a_date_is_named(mcp_owner, make_token):
    token = await sync_to_async(make_token)(AGENT)

    body = json.dumps(parse(await _tool(token, "list_advisory_proposals", since="last tuesday")))

    assert "ISO 8601" in body
