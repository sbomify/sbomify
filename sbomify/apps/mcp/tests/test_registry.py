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
    "upload_sbom",
    "upload_vex",
    "create_release",
    "tag_artifact_to_release",
    "create_contact_profile",
    "update_contact_profile",
    "assign_contact_profile",
}


def test_every_declared_action_is_known_to_can():
    """A typo in a tool's action would otherwise 403 that tool forever."""
    registry.validate()

    unknown = {name: spec.action for name, spec in registry.all_specs().items() if spec.action not in ALL_ACTIONS}
    assert unknown == {}


def test_all_tools_are_registered():
    """Pins the surface: adding or removing a tool is a deliberate change."""
    specs = registry.all_specs()

    assert len(specs) == 24
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

    assert {"upload_sbom", "create_release", "tag_artifact_to_release"} <= allowed
    assert "upload_vex" not in allowed
    # 'publish' includes release:read for the check-then-create workflow.
    assert "get_release" in allowed
    assert "list_products" not in allowed
    # ... but release:read alone must not unlock the workspace's security
    # posture: the risk report also requires workspace:read.
    assert "get_release_risk_report" not in allowed


def test_resource_wildcard_scope():
    allowed = registry.permitted_by(["sbom:*"])

    assert {"get_sbom", "list_sboms", "get_sbom_packages", "get_assessments"} == allowed


@pytest.mark.parametrize(
    ("scope", "tool"),
    [
        ("workspace:read", "get_workspace_summary"),
        ("product:read", "list_products"),
        ("component:read_internal", "get_component"),
        ("release:read", "get_release"),
        ("document:read", "list_documents"),
        ("artifact:publish", "upload_sbom"),
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
