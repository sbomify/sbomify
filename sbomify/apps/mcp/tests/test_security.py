"""Adversarial tests for the MCP endpoint.

The MCP server is a higher-risk surface than the REST API because the caller is
an LLM whose inputs are frequently attacker-influenced. These tests encode the
properties that must hold even when the agent is actively being manipulated, and
are the ones to extend first when a new tool is added.

Layered defences under test here:

1. Token scopes cannot be widened by anything the caller says.
2. Destructive and administrative actions have no tool at all.
3. Resource caps bound what a coerced agent can consume.
4. Workspace boundaries hold against direct-ID probing.
5. Errors do not disclose whether a resource exists elsewhere.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.core.authz import ALL_ACTIONS, SCOPE_PRESETS
from sbomify.apps.mcp import limits, registry
from sbomify.apps.mcp.server import build_app

from .test_protocol import call, mcp_http, parse

build_app()


# --------------------------------------------------------------------------
# 1. Scope integrity — the real boundary
# --------------------------------------------------------------------------


def test_no_tool_exposes_a_destructive_or_administrative_action():
    """The strongest guarantee: "delete all our SBOMs" has no tool to reach for.

    Scopes alone would be enough for a well-behaved token, but a compromised or
    over-scoped one plus a prompt injection is exactly the scenario this closes.
    """
    exposed = {spec.action for spec in registry.all_specs().values()}

    assert exposed & registry.FORBIDDEN_ACTIONS == set()
    assert not any(action.endswith(":delete") for action in exposed)
    assert "workspace:administer" not in exposed
    assert "billing:manage" not in exposed
    assert "member:manage" not in exposed


def test_registering_a_destructive_tool_is_rejected():
    """A future contributor cannot add a delete tool without tripping this."""
    with pytest.raises(ValueError, match="not exposable over MCP"):
        registry.register("delete_everything", "sbom:delete")


def test_forbidden_actions_are_real_actions():
    """Guards against the deny-list silently emptying if authz renames verbs."""
    assert registry.FORBIDDEN_ACTIONS <= ALL_ACTIONS
    assert len(registry.FORBIDDEN_ACTIONS) >= 6


def test_read_only_preset_exposes_no_writing_tool():
    """Checked via the `writes` flag, independently of the action allow-list."""
    allowed = registry.permitted_by(SCOPE_PRESETS["read_only"])
    writers = {name for name, spec in registry.all_specs().items() if spec.writes}

    assert allowed & writers == set()


def test_profile_writes_are_absent_from_both_default_presets():
    """Profile management needs a deliberately scoped token."""
    profile_writes = {"create_contact_profile", "update_contact_profile", "assign_contact_profile"}

    assert registry.permitted_by(SCOPE_PRESETS["read_only"]) & profile_writes == set()
    assert registry.permitted_by(SCOPE_PRESETS["publish"]) & profile_writes == set()


# --------------------------------------------------------------------------
# 2. Resource caps
# --------------------------------------------------------------------------


def test_oversized_upload_is_refused_before_parsing():
    from mcp.server.fastmcp.exceptions import ToolError

    oversized = b"x" * (limits.MAX_UPLOAD_BYTES + 1)

    with pytest.raises(ToolError, match="over the"):
        limits.enforce_upload_size(oversized, label="SBOM")


def test_oversized_stored_artifact_is_not_parsed():
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="too large to inspect"):
        limits.enforce_parse_size(b"x" * (limits.MAX_ARTIFACT_PARSE_BYTES + 1), sbom_id="abc")


def test_oversized_response_is_refused():
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="over the"):
        limits.enforce_response_size({"blob": "x" * (limits.MAX_RESPONSE_BYTES + 1)}, tool="list_products")


def test_response_under_the_cap_passes_through_unchanged():
    payload = {"items": [1, 2, 3]}

    assert limits.enforce_response_size(payload, tool="list_products") is payload


def test_untrusted_text_is_truncated():
    """Bounds how much injected text one artifact field can carry to the model."""
    assert limits.untrusted("a" * 10, limit=100) == "a" * 10
    assert limits.untrusted(None) is None

    truncated = limits.untrusted("a" * 5000, limit=100)
    assert len(truncated) < 200
    assert truncated.endswith("[truncated by sbomify]")


# --------------------------------------------------------------------------
# 3. Live probing over the transport
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_unauthenticated_caller_is_offered_no_tools():
    """A caller with no token can do nothing, so it is shown nothing."""
    async with mcp_http() as client:
        response = await call(client, "tools/list")

    assert parse(response)["result"]["tools"] == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_invalid_token_is_offered_no_tools(make_token):
    async with mcp_http() as client:
        response = await call(client, "tools/list", token="clearly-not-a-valid-token")

    assert parse(response)["result"]["tools"] == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_expired_token_cannot_call_a_tool(mcp_owner, make_token):
    from datetime import timedelta

    from django.utils import timezone

    token = await sync_to_async(make_token)(None)

    def expire() -> None:
        token.expires_at = timezone.now() - timedelta(days=1)
        token.save(update_fields=["expires_at"])

    await sync_to_async(expire)()

    async with mcp_http() as client:
        response = await call(client, "tools/call", token=token.encoded_token, name="list_products", arguments={})

    assert "Invalid or expired" in json.dumps(parse(response))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_scope_cannot_be_widened_by_calling_a_hidden_tool(make_token, product_in_bound_workspace):
    """The central claim: what a token may do is fixed by the token, not the call.

    A read-only token is not shown the write tools, but naming one directly must
    still be refused — this is what stops a prompt injection from turning a
    reporting agent into a publishing one.
    """
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        # Arguments must be schema-valid: FastMCP validates them before the tool
        # body (and so before the scope gate) runs, and an argument error would
        # mask the refusal this test is about.
        for name, arguments in (
            ("upload_sbom", {"component_id": "x", "content": "{}"}),
            ("create_release", {"product_id": product_in_bound_workspace.id, "name": "v9"}),
            ("create_contact_profile", {"name": "Injected Supplier", "email": "injected@example.com"}),
        ):
            response = await call(client, "tools/call", token=token.encoded_token, name=name, arguments=arguments)
            body = json.dumps(parse(response))
            assert "Not permitted" in body or "token scope does not grant" in body, (name, body)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_scope_is_refused_before_the_tool_body_runs(make_token):
    """Regression: the declared action must be enforced by the wrapper itself.

    The publishing and profile tools delegate to REST views that load their
    resource *before* calling ``can()``, so a nonexistent id used to yield a 404
    — meaning the registry's declared action never got checked on that path. The
    scope gate in ``mcp_tool`` now refuses first, so an out-of-scope call is
    denied whether or not the target exists.
    """
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        response = await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="upload_sbom",
            arguments={"component_id": "no-such-component", "content": "{}"},
        )

    body = json.dumps(parse(response))
    assert "token scope does not grant" in body, body
    # Must not leak whether the component exists — the refusal comes first.
    assert "not found" not in body.lower(), body


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_publish_token_cannot_read_the_catalogue(make_token, product_in_bound_workspace):
    """Scopes narrow in both directions: a CI-style token is not a reader."""
    token = await sync_to_async(make_token)(SCOPE_PRESETS["publish"])

    async with mcp_http() as client:
        response = await call(client, "tools/call", token=token.encoded_token, name="list_products", arguments={})

    assert "Not permitted" in json.dumps(parse(response))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cross_workspace_probing_is_indistinguishable_from_absence(make_token, product_in_other_workspace):
    """A resource in another workspace must look exactly like one that does not exist.

    Differing messages would let a caller enumerate IDs across tenants.
    """
    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

    async with mcp_http() as client:
        real_elsewhere = await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="get_product",
            arguments={"product_id": product_in_other_workspace.id},
        )
        nonexistent = await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="get_product",
            arguments={"product_id": "does-not-exist"},
        )

    def message(response):
        text = json.dumps(parse(response))
        return text.replace(product_in_other_workspace.id, "ID").replace("does-not-exist", "ID")

    assert message(real_elsewhere) == message(nonexistent)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_token_for_another_workspace_cannot_write_to_this_one(
    mcp_owner, make_token, product_in_bound_workspace
):
    """Workspace pinning holds for writes even though the user owns both."""
    _, _, other = mcp_owner
    token = await sync_to_async(make_token)(None, other)

    async with mcp_http() as client:
        response = await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="create_release",
            arguments={"product_id": product_in_bound_workspace.id, "name": "v1"},
        )

    assert "No product found" in json.dumps(parse(response))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_unknown_tool_name_is_rejected_cleanly(make_token):
    """A hallucinated tool name must not 500."""
    token = await sync_to_async(make_token)(None)

    async with mcp_http() as client:
        response = await call(client, "tools/call", token=token.encoded_token, name="drop_all_tables", arguments={})

    assert response.status_code == 200
    assert "drop_all_tables" in json.dumps(parse(response))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_malformed_json_rpc_does_not_500(make_token):
    token = await sync_to_async(make_token)(None)

    async with mcp_http() as client:
        response = await client.post(
            "http://localhost/mcp",
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
                "authorization": f"Bearer {token.encoded_token}",
            },
            content="{not json at all",
        )

    assert response.status_code < 500, response.text


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_oversized_upload_is_refused_over_the_transport(make_token, mcp_owner):
    """The cap holds through the real call path, not just the helper."""
    from sbomify.apps.core.models import Component

    _, bound, _ = mcp_owner
    component = await sync_to_async(Component.objects.create)(name="Target", team=bound)
    token = await sync_to_async(make_token)(["artifact:publish"])

    # Comfortably over the cap without building the string byte-by-byte.
    payload = '{"padding":"' + "x" * (limits.MAX_UPLOAD_BYTES + 1024) + '"}'

    async with mcp_http() as client:
        response = await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="upload_sbom",
            arguments={"component_id": component.id, "content": payload},
        )

    # Two refusal paths, depending on the SDK. mcp >= 1.29 caps the request
    # body in StreamableHTTPSessionManager and answers a plain-text 413 before
    # the tool runs; earlier versions let the body through and the tool itself
    # rejects it with a JSON-RPC error naming the cap. Both satisfy what this
    # test is for, so assert the property — the oversized upload is refused —
    # rather than one version's wording.
    if response.status_code == 413:
        assert "too large" in response.text.lower()
    else:
        assert "limit for MCP uploads" in json.dumps(parse(response))


# --------------------------------------------------------------------------
# 4. Declared action == required action
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_tool_works_with_a_token_scoped_to_exactly_its_declared_action(
    make_token, component_in_bound_workspace, product_in_bound_workspace
):
    """The registry's promise: the declared action is sufficient to call the tool.

    `tools/list` advertises a tool whenever the token grants its declared
    action, so a tool that internally demands some *other* action is advertised
    and then refused — the exact guaranteed-to-fail advertised call that
    scope-filtered listing exists to prevent.

    Not-found is a fine outcome here (the fixtures do not set up every
    resource); a permission refusal is not.
    """
    from sbomify.apps.core.models import Release

    release = await sync_to_async(Release.objects.create)(product=product_in_bound_workspace, name="v1", version="1")

    cases = [
        ("list_sboms", "sbom:read", {"component_id": component_in_bound_workspace.id}),
        ("list_documents", "document:read", {"component_id": component_in_bound_workspace.id}),
        ("tag_artifact_to_release", "release:tag", {"release_id": release.id, "sbom_id": "nope"}),
        (
            "assign_contact_profile",
            "component:manage",
            {"component_id": component_in_bound_workspace.id, "profile_id": "nope"},
        ),
    ]

    async with mcp_http() as client:
        for name, action, arguments in cases:
            token = await sync_to_async(make_token)([action])
            response = await call(client, "tools/call", token=token.encoded_token, name=name, arguments=arguments)
            body = json.dumps(parse(response))
            assert "token scope does not grant" not in body, (name, action, body)
            assert "Not permitted" not in body, (name, action, body)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_guest_members_token_is_refused(mcp_owner, make_token, product_in_bound_workspace):
    """REST 403s guest members on every internal read; MCP must not be the laxer door.

    Tokens are minted while owner/admin (creation is role-gated) but survive a
    demotion to guest — nothing revokes them on role change, so the gate has to
    hold at call time.
    """
    from sbomify.apps.teams.models import Member

    user, bound, _ = mcp_owner
    token = await sync_to_async(make_token)(None)

    def demote() -> None:
        Member.objects.filter(user=user, team=bound).update(role="guest")

    await sync_to_async(demote)()

    async with mcp_http() as client:
        response = await call(client, "tools/call", token=token.encoded_token, name="list_products", arguments={})

    assert "Guest members" in json.dumps(parse(response))
