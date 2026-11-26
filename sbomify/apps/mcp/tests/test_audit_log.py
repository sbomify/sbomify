"""Agents acting over MCP land in the workspace audit log under the person they act for."""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.audit.models import ActorType, AuditEvent, Channel, Outcome

from .test_protocol import call, mcp_http


def _enterprise(workspace) -> None:
    workspace.billing_plan = "enterprise"
    workspace.save(update_fields=["billing_plan"])


def _events(workspace) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(workspace_id=workspace.pk).order_by("id"))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_write_tool_records_the_change_and_the_call(mcp_owner, make_token):
    user, bound, _ = mcp_owner
    await sync_to_async(_enterprise)(bound)
    token = await sync_to_async(make_token)(["workspace:manage", "workspace:read"])

    async with mcp_http() as client:
        await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="create_contact_profile",
            arguments={"name": "ACME Corp", "email": "security@acme.example"},
        )

    recorded = await sync_to_async(_events)(bound)
    by_action = {event.action: event for event in recorded}

    created = by_action["contact_profile.created"]
    assert created.actor_type == ActorType.AGENT
    assert created.actor_user_id == user.pk
    assert created.channel == Channel.MCP
    assert created.credential_id == str(token.pk)
    assert created.target_label == "ACME Corp"

    tool_call = by_action["agent.tool_call"]
    assert tool_call.outcome == Outcome.SUCCESS
    assert tool_call.target_id == "create_contact_profile"
    assert tool_call.metadata == {"tool": "create_contact_profile", "writes": True}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_refused_tool_call_is_recorded_as_denied(mcp_owner, make_token):
    _, bound, _ = mcp_owner
    await sync_to_async(_enterprise)(bound)
    token = await sync_to_async(make_token)(["workspace:read"])

    async with mcp_http() as client:
        await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="create_contact_profile",
            arguments={"name": "ACME Corp", "email": "security@acme.example"},
        )

    [event] = await sync_to_async(_events)(bound)
    assert event.action == "agent.tool_call"
    assert event.outcome == Outcome.DENIED
