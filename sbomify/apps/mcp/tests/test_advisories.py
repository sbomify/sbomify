"""The advisory tools report the two status axes without conflating them.

The service projection an advisory page renders calls the remediation state
``status`` and the publication state ``publication_status``. Handed straight to
an agent that reads names literally, ``status: affected`` says nothing about
whether a customer can see the advisory. These pin the renaming, the workspace
scope, and that creating one yields a draft rather than a publication.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from sbomify.apps.security_advisories.models import SecurityAdvisory

from .test_protocol import call, mcp_http, parse, structured


def _advisory(team, title: str, **kwargs) -> SecurityAdvisory:
    """One advisory, satisfying the model's own publication constraints.

    A published row must carry a tracking id and a published_at, which the
    model validates on save, so publishing here means setting all three.
    """
    if kwargs.get("status") == SecurityAdvisory.Status.PUBLISHED:
        kwargs.setdefault("tracking_id", f"SBOM-{abs(hash(title)) % 10000:04d}")
        kwargs.setdefault("published_at", timezone.now())
    return SecurityAdvisory.objects.create(team=team, title=title, **kwargs)


async def _tool(token, name, **arguments):
    async with mcp_http() as client:
        return await call(client, "tools/call", token=token.encoded_token, name=name, arguments=arguments)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_the_two_status_axes_are_named_in_full(mcp_owner, make_token):
    """A published advisory whose fix is still outstanding must read as both."""
    _, bound, _ = mcp_owner
    await sync_to_async(_advisory)(
        bound,
        "Heap overflow in libexample",
        status=SecurityAdvisory.Status.PUBLISHED,
        remediation_status="fix_in_progress",
    )
    token = await sync_to_async(make_token)(["advisory:read"])

    payload = structured(await _tool(token, "list_advisories"))

    row = next(item for item in payload["items"] if item["title"] == "Heap overflow in libexample")
    assert row["publication_status"] == "published"
    assert row["remediation_status"] == "fix_in_progress"
    assert "status" not in row, "the bare name is the one that reads backwards"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_publication_status_filters_and_an_unknown_one_is_named(mcp_owner, make_token):
    _, bound, _ = mcp_owner
    await sync_to_async(_advisory)(bound, "A draft", status=SecurityAdvisory.Status.DRAFT)
    await sync_to_async(_advisory)(bound, "A published one", status=SecurityAdvisory.Status.PUBLISHED)
    token = await sync_to_async(make_token)(["advisory:read"])

    drafts = structured(await _tool(token, "list_advisories", publication_status="draft"))
    assert [row["title"] for row in drafts["items"]] == ["A draft"]

    body = json.dumps(parse(await _tool(token, "list_advisories", publication_status="nonsense")))
    assert "Unknown publication_status" in body
    assert "withdrawn" in body, "the message should list what is valid"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_another_workspaces_advisory_reads_as_absent(mcp_owner, make_token):
    """Not forbidden: a workspace must not learn that an id exists elsewhere."""
    _, _, other = mcp_owner
    theirs = await sync_to_async(_advisory)(other, "Not yours")
    token = await sync_to_async(make_token)(["advisory:read"])

    body = json.dumps(parse(await _tool(token, "get_advisory", advisory_id=theirs.id)))

    assert "no advisory found" in body.lower()
    assert "Not yours" not in body


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_creating_an_advisory_yields_a_draft(mcp_owner, make_token):
    """The tool cannot publish, so what it makes must not arrive published."""
    token = await sync_to_async(make_token)(["advisory:manage"])

    created = structured(await _tool(token, "create_advisory", title="Draft from an agent", severity="high"))

    assert created["publication_status"] == "draft"
    assert not created.get("published_at")
    stored = await sync_to_async(SecurityAdvisory.objects.get)(title="Draft from an agent")
    assert stored.status == SecurityAdvisory.Status.DRAFT


def test_the_publication_states_match_the_model():
    """PUBLICATION_STATES is hand-written to keep the module's imports lazy."""
    from sbomify.apps.mcp.tools.advisories import PUBLICATION_STATES

    assert set(PUBLICATION_STATES) == set(SecurityAdvisory.Status.values)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_page_costs_one_page_of_projections(mcp_owner, make_token):
    """Projecting the whole workspace to show one page is what this avoids.

    Each projection sorts the advisory's events, computes worst severity and
    CVSS, and walks a four-way prefetch, so the cost is per row rather than per
    page unless the slice happens in the database.
    """
    _, bound, _ = mcp_owner
    for index in range(8):
        await sync_to_async(_advisory)(bound, f"advisory-{index:02d}")
    token = await sync_to_async(make_token)(["advisory:read"])

    projected: list[Any] = []
    from sbomify.apps.security_advisories.services import advisories as service

    original = service._advisory_projection
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        service,
        "_advisory_projection",
        lambda advisory, **kw: projected.append(advisory.id) or original(advisory, **kw),
    )
    try:
        payload = structured(await _tool(token, "list_advisories", page=1, page_size=3))
    finally:
        monkey.undo()

    assert payload["total"] == 8
    assert len(payload["items"]) == 3
    assert len(projected) == 3, f"projected {len(projected)} rows to return 3"
