"""Tool registry: maps each MCP tool to the ``can()`` action it requires.

Two things depend on this mapping:

1. **Listing.** ``tools/list`` is filtered to the actions the caller's token
   scopes permit, so an agent holding a ``read_only`` token never sees
   ``upload_sbom``. That removes a whole class of guaranteed-to-fail calls and
   the wasted agent turns that follow them.
2. **Enforcement.** Every invocation still calls ``can()`` against the concrete
   resource (``auth.require``). Filtering the list is an ergonomics win, never
   the security boundary — a client is free to call a tool it was not shown, and
   that call is denied exactly as the REST API would deny it.

The declared action must be a member of ``authz.ALL_ACTIONS``; ``validate()``
enforces that at startup so a typo fails loudly instead of silently denying
every call.
"""

from __future__ import annotations

from dataclasses import dataclass

from sbomify.apps.core.authz import ALL_ACTIONS, scope_permits


@dataclass(frozen=True)
class ToolSpec:
    """Registration metadata for one MCP tool."""

    name: str
    action: str
    """The ``can()`` action this tool needs, e.g. ``"sbom:read"``."""

    also_requires: tuple[str, ...] = ()
    """Extra actions the delegated view checks besides ``action``. A token must
    hold every one for the tool to be advertised or invoked — otherwise the
    registry would advertise a tool the view is certain to refuse (the VEX
    upload view gates on ``artifact:publish`` before ``artifact:publish_vex``)."""

    writes: bool = False
    """Whether the tool mutates state. Drives the stricter write throttle, and
    lets tests assert that the read-only preset exposes nothing that writes."""

    @property
    def actions(self) -> tuple[str, ...]:
        return (self.action, *self.also_requires)


_REGISTRY: dict[str, ToolSpec] = {}

# Actions a tool may never require. Destructive verbs are excluded by
# construction rather than by scope alone: an agent acting on injected
# instructions cannot reach for a tool that was never registered, whatever its
# token permits. Deletion stays a deliberate human action in the UI or REST API.
FORBIDDEN_ACTIONS: frozenset[str] = frozenset(
    action for action in ALL_ACTIONS if action.split(":", 1)[1] in ("delete", "administer")
)


def register(name: str, action: str, *, also_requires: tuple[str, ...] = (), writes: bool = False) -> ToolSpec:
    """Record that ``name`` requires ``action`` (and ``also_requires``). Returns the stored spec."""
    if name in _REGISTRY:
        raise ValueError(f"MCP tool {name!r} is already registered")
    spec = ToolSpec(name=name, action=action, also_requires=also_requires, writes=writes)
    for required in spec.actions:
        if required in FORBIDDEN_ACTIONS:
            raise ValueError(
                f"MCP tool {name!r} requires {required!r}, which is not exposable over MCP. "
                "Destructive and administrative actions are deliberately absent from the tool surface."
            )
    _REGISTRY[name] = spec
    return spec


def get(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def all_specs() -> dict[str, ToolSpec]:
    return dict(_REGISTRY)


def validate() -> None:
    """Raise if any registered tool names an action ``can()`` doesn't know.

    Called at import time from ``server.py`` and asserted again in tests, so an
    action rename in ``authz`` that misses a tool breaks the build rather than
    turning that tool into a permanent 403.
    """
    unknown = {
        spec.name: [action for action in spec.actions if action not in ALL_ACTIONS]
        for spec in _REGISTRY.values()
        if any(action not in ALL_ACTIONS for action in spec.actions)
    }
    if unknown:
        raise ValueError(f"MCP tools declare actions unknown to can(): {unknown}")


def permitted_by(scopes: list[str] | None) -> set[str]:
    """Names of the tools a token with ``scopes`` could invoke.

    ``None`` means an unscoped (legacy, full-capability) token, which permits
    every tool. Delegates to ``authz.scope_permits`` rather than
    re-implementing the ``<resource>:*`` wildcard grammar, so the two can't
    drift. A tool with several required actions is permitted only when the
    token grants all of them — matching what its delegated view will enforce.
    """
    return {spec.name for spec in _REGISTRY.values() if all(scope_permits(scopes, action) for action in spec.actions)}
