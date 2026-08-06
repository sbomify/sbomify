"""Happy-path tests for the tools that mutate state.

These exist because their absence let a completely broken tool ship: the first
version of ``assign_contact_profile`` raised ``AttributeError`` on *every* call
(it handed a stub ``HttpRequest`` with no body to a view that logs
``request.body`` in an eagerly-evaluated f-string), and the suite was green
because every test that named the tool only asserted registry and scope facts
about it. Nothing actually invoked it.

So: every write tool is called here for real, against real rows, and its effect
is checked in the database. Scope and workspace *refusals* are covered in
``test_security``; this file is about the calls that are supposed to work.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.core.authz import SCOPE_PRESETS

from .test_protocol import call, mcp_http, parse, structured

MINIMAL_CYCLONEDX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.6",
    "version": 1,
    "metadata": {"component": {"type": "application", "name": "widget", "version": "1.2.3"}},
    "components": [],
}


async def call_tool(client, token, tool_name, arguments):
    """Invoke one tool.

    ``arguments`` is passed as a dict rather than ``**kwargs`` because several
    tools take an argument literally called ``name``, which would collide with
    the JSON-RPC ``name`` field.
    """
    return await call(client, "tools/call", token=token.encoded_token, name=tool_name, arguments=arguments)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_assign_contact_profile_actually_assigns(
    make_token, component_in_bound_workspace, contact_profile_in_bound_workspace
):
    """Regression: this tool raised AttributeError on every call.

    ``patch_component_metadata`` logs ``request.body`` in an f-string that is
    evaluated regardless of log level, and a bare ``HttpRequest()`` has no
    ``_body``/``_read_started``. ``auth._stub_request`` now seeds an empty body.
    """
    from sbomify.apps.core.models import Component

    token = await sync_to_async(make_token)(["component:manage", "component:read_internal", "workspace:read"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "assign_contact_profile",
            {
                "component_id": component_in_bound_workspace.id,
                "profile_id": contact_profile_in_bound_workspace.id,
            },
        )

    result = structured(response)
    assert result["assigned"] is True

    refreshed = await sync_to_async(Component.objects.get)(pk=component_in_bound_workspace.id)
    assert refreshed.contact_profile_id == contact_profile_in_bound_workspace.id


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_create_and_list_contact_profile(make_token):
    token = await sync_to_async(make_token)(["workspace:manage", "workspace:read"])

    async with mcp_http() as client:
        created = await call_tool(
            client,
            token,
            "create_contact_profile",
            {
                "name": "ACME Corp",
                "email": "security@acme.example",
                "website_url": "https://acme.example",
            },
        )
        listed = await call_tool(client, token, "list_contact_profiles", {})

    profile = structured(created)
    assert profile["name"] == "ACME Corp"

    names = [p["name"] for p in structured(listed)["profiles"]]
    assert "ACME Corp" in names


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_contact_profile_renames(make_token, contact_profile_in_bound_workspace):
    from sbomify.apps.teams.models import ContactProfile

    token = await sync_to_async(make_token)(["workspace:manage", "workspace:read"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "update_contact_profile",
            {
                "profile_id": contact_profile_in_bound_workspace.id,
                "name": "Renamed Supplier",
            },
        )

    assert structured(response)["name"] == "Renamed Supplier"

    refreshed = await sync_to_async(ContactProfile.objects.get)(pk=contact_profile_in_bound_workspace.id)
    assert refreshed.name == "Renamed Supplier"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_publish_preset_can_create_a_release(make_token, product_in_bound_workspace):
    """Regression: create_release required product:read, which `publish` lacks.

    The preset exists for exactly this workflow, so a publish-scoped token being
    shown the tool and then refused was the guaranteed-to-fail advertised call
    that scope-filtered listing is supposed to eliminate.
    """
    from sbomify.apps.core.models import Release

    token = await sync_to_async(make_token)(SCOPE_PRESETS["publish"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "create_release",
            {
                "product_id": product_in_bound_workspace.id,
                "name": "v1.0.0",
                "version": "1.0.0",
            },
        )

    result = structured(response)
    assert result.get("name") == "v1.0.0"

    exists = await sync_to_async(Release.objects.filter(product=product_in_bound_workspace, name="v1.0.0").exists)()
    assert exists


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_upload_sbom_stores_the_artifact(make_token, component_in_bound_workspace, monkeypatch):
    """Uploads reach the real REST view; S3 is stubbed so no bucket is needed."""
    from sbomify.apps.core import object_store
    from sbomify.apps.sboms.models import SBOM

    monkeypatch.setattr(object_store.S3Client, "upload_sbom", lambda self, data: "stub-key.json", raising=False)

    token = await sync_to_async(make_token)(["artifact:publish"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "upload_sbom",
            {
                "component_id": component_in_bound_workspace.id,
                "content": json.dumps(MINIMAL_CYCLONEDX),
            },
        )

    assert "id" in structured(response)

    stored = await sync_to_async(list)(SBOM.objects.filter(component=component_in_bound_workspace))
    assert len(stored) == 1
    assert stored[0].format == "cyclonedx"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_upload_sbom_rejects_a_component_in_another_workspace(
    make_token, component_in_other_workspace, monkeypatch
):
    """Writes must be confined to the token's workspace, as reads already are."""
    from sbomify.apps.core import object_store
    from sbomify.apps.sboms.models import SBOM

    monkeypatch.setattr(object_store.S3Client, "upload_sbom", lambda self, data: "stub-key.json", raising=False)

    token = await sync_to_async(make_token)(["artifact:publish"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "upload_sbom",
            {
                "component_id": component_in_other_workspace.id,
                "content": json.dumps(MINIMAL_CYCLONEDX),
            },
        )

    assert "No component found" in json.dumps(parse(response))

    count = await sync_to_async(SBOM.objects.filter(component=component_in_other_workspace).count)()
    assert count == 0


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_upload_sbom_rejects_malformed_json(make_token, component_in_bound_workspace):
    token = await sync_to_async(make_token)(["artifact:publish"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "upload_sbom",
            {
                "component_id": component_in_bound_workspace.id,
                "content": "{definitely not json",
            },
        )

    assert "not valid JSON" in json.dumps(parse(response))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_upload_sbom_rejects_an_unknown_format(make_token, component_in_bound_workspace):
    token = await sync_to_async(make_token)(["artifact:publish"])

    async with mcp_http() as client:
        response = await call_tool(
            client,
            token,
            "upload_sbom",
            {
                "component_id": component_in_bound_workspace.id,
                "content": json.dumps(MINIMAL_CYCLONEDX),
                "sbom_format": "swid",
            },
        )

    assert "Unsupported sbom_format" in json.dumps(parse(response))
