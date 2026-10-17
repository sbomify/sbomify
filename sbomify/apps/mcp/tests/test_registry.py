"""Registry integrity and scope-driven tool filtering.

These are the security-critical unit tests for the MCP server: they pin the
mapping from tool to ``can()`` action, and assert that a narrowly scoped token
is only ever offered the tools it could actually invoke.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core.authz import ALL_ACTIONS, SCOPE_PRESETS
from sbomify.apps.mcp import registry
from sbomify.apps.mcp.server import build_app

# Importing the app registers every tool. Idempotent across tests: build_app()
# raises on duplicate registration, so call it once at module import.
build_app()

WRITE_TOOLS = {
    "upload_artifact",
    "upload_vex",
    "create_release",
    "tag_artifact_to_release",
    "create_contact_profile",
    "update_contact_profile",
    "assign_contact_profile",
    "create_advisory",
}


def test_every_declared_action_is_known_to_can():
    """A typo in a tool's action would otherwise 403 that tool forever."""
    registry.validate()

    unknown = {name: spec.action for name, spec in registry.all_specs().items() if spec.action not in ALL_ACTIONS}
    assert unknown == {}


def test_all_tools_are_registered():
    """Pins the surface: adding or removing a tool is a deliberate change."""
    specs = registry.all_specs()

    assert len(specs) == 28
    assert WRITE_TOOLS <= set(specs)
    assert {spec.name for spec in specs.values() if spec.writes} == WRITE_TOOLS


def test_unscoped_token_gets_every_tool():
    """``scopes=None`` is the legacy full-capability token."""
    assert registry.permitted_by(None) == set(registry.all_specs())


def test_wildcard_scope_gets_every_tool():
    assert registry.permitted_by(["*"]) == set(registry.all_specs())


def test_empty_scope_gets_nothing():
    assert registry.permitted_by([]) == set()


def test_read_only_preset_excludes_every_write_tool():
    """The headline guarantee: a read-only agent is never shown a mutation."""
    allowed = registry.permitted_by(SCOPE_PRESETS["read_only"])

    assert allowed & WRITE_TOOLS == set()
    assert "list_products" in allowed
    assert "get_release_risk_report" in allowed


def test_publish_preset_grants_upload_and_release_but_not_vex():
    """VEX takes the stricter ``artifact:publish_vex``, which 'publish' omits."""
    allowed = registry.permitted_by(SCOPE_PRESETS["publish"])

    assert {"upload_artifact", "create_release", "tag_artifact_to_release"} <= allowed
    assert "upload_vex" not in allowed
    # 'publish' includes release:read for the check-then-create workflow.
    assert "get_release" in allowed
    assert "list_products" not in allowed
    # ... but release:read alone must not unlock the workspace's security
    # posture: the risk report also requires workspace:read.
    assert "get_release_risk_report" not in allowed


def test_resource_wildcard_scope():
    allowed = registry.permitted_by(["sbom:*"])

    assert {"get_artifact", "list_artifacts", "get_artifact_packages", "get_assessments"} == allowed


def test_advisory_scope_reaches_the_reads_but_not_a_publish_tool():
    """Publishing an advisory is a public statement, so no tool offers it.

    A token carrying advisory:publish must therefore be advertised nothing
    extra, which is the check that would fail if one were added without the
    decision in advisories.py being revisited.
    """
    assert registry.permitted_by(["advisory:read"]) == {"list_advisories", "get_advisory"}
    assert registry.permitted_by(["advisory:publish"]) == set()


def test_document_scope_reaches_both_document_tools():
    """Documents are the other half of the artifact surface, and a token scoped
    to them must reach the detail read as well as the listing."""
    assert registry.permitted_by(["document:read"]) == {"list_documents", "get_document"}


@pytest.mark.parametrize(
    ("scope", "tool"),
    [
        ("workspace:read", "get_workspace_summary"),
        ("product:read", "list_products"),
        ("component:read_internal", "get_component"),
        ("release:read", "get_release"),
        ("document:read", "list_documents"),
        ("artifact:publish", "upload_artifact"),
        ("release:create", "create_release"),
        ("release:tag", "tag_artifact_to_release"),
    ],
)
def test_single_scope_grants_exactly_its_tools(scope, tool):
    allowed = registry.permitted_by([scope])

    assert tool in allowed
    assert all(registry.get(name).action == scope for name in allowed)


def test_upload_vex_needs_both_publish_scopes():
    """The VEX view checks artifact:publish before artifact:publish_vex, so a
    publish_vex-only token must not be advertised a tool the view will 403."""
    assert "upload_vex" not in registry.permitted_by(["artifact:publish_vex"])
    assert "upload_vex" not in registry.permitted_by(["artifact:publish"])
    assert "upload_vex" in registry.permitted_by(["artifact:publish", "artifact:publish_vex"])


def test_duplicate_registration_is_rejected():
    with pytest.raises(ValueError, match="already registered"):
        registry.register("list_products", "product:read")


@pytest.mark.asyncio
async def test_every_tool_publishes_its_behaviour_hints():
    """A client reads these to decide whether to interrupt the user.

    readOnlyHint lets a well-behaved client run the twenty reads without a
    prompt, and it is derived from the same `writes` flag the write throttle
    uses, so the two can never disagree.
    """
    from sbomify.apps.mcp.server import mcp

    tools = await mcp.list_tools()
    specs = registry.all_specs()

    assert tools, "no tools registered"
    for tool in tools:
        annotations = tool.annotations
        assert annotations is not None, tool.name
        assert annotations.readOnlyHint is (not specs[tool.name].writes), tool.name
        # The registry refuses destructive and outward-facing actions at
        # registration, so this is a property of the surface, not a per-tool
        # judgement. Every tool also stays inside one workspace's own data.
        assert annotations.destructiveHint is False, tool.name
        assert annotations.openWorldHint is False, tool.name


@pytest.mark.asyncio
async def test_idempotency_is_only_claimed_where_a_repeat_is_a_no_op():
    """The spec says idempotentHint is meaningful only for a write, and a wrong
    claim is worse than none: a client that believes a failed call is safe to
    retry will re-run it."""
    from sbomify.apps.mcp.server import mcp

    hints = {t.name: t.annotations.idempotentHint for t in await mcp.list_tools()}

    assert {name for name, hint in hints.items() if hint is True} == {
        "update_contact_profile",
        "assign_contact_profile",
    }
    # Every read leaves it unset rather than claiming True, which would be
    # meaningless against readOnlyHint.
    assert all(hints[spec.name] is None for spec in registry.all_specs().values() if not spec.writes)
    # Uploading twice is a 409 on the duplicate guard, and tagging an artifact
    # already in the release is a 409 too.
    assert hints["upload_artifact"] is False
    assert hints["tag_artifact_to_release"] is False
