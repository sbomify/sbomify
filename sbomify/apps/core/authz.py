"""Single authorization decision point.

``can(actor, action, resource)`` is the one front door for authorization. It maps
a named ``action`` to the capability the codebase already enforces, then
**delegates** to the existing checks — ``verify_item_access`` (role-based) and
``check_component_access`` (resource-attribute-based) — so its decision is
identical to the scattered inline role checks it is meant to replace.

This is the first phase of consolidating authorization: introduce the facade
with no behaviour change. Later work migrates call sites onto ``can`` and grows
the action catalog / capability model; until then both styles coexist.

Why a facade instead of a rewrite: every call site today passes a raw role list
(``["owner", "admin"]``) to ``verify_item_access``. Naming the role sets as
capabilities and giving each action one definition turns "what can an admin do"
from an emergent property of ~170 call sites into a single table here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest

# Roles — mirror the keys of ``settings.TEAMS_SUPPORTED_ROLES``.
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_GUEST = "guest"
ROLE_BOT = "bot"

# Capability tiers: the role sets the current checks grant. Each is exactly an
# ``allowed_roles`` list used at today's call sites, so an action that maps to a
# tier is behaviour-identical to the inline check it replaces.
ADMINISTER: tuple[str, ...] = (ROLE_OWNER,)
"""Owner-only: billing, member management, workspace settings/deletion."""

MANAGE: tuple[str, ...] = (ROLE_OWNER, ROLE_ADMIN)
"""Create/update/delete products, components, releases, and artifact metadata."""

PUBLISH: tuple[str, ...] = (ROLE_OWNER, ROLE_ADMIN, ROLE_BOT)
"""Upload artifacts — also granted to OIDC/CI ``bot`` identities."""

# Order mirrors the predominant call-site literal ``["guest", "owner", "admin"]``
# (membership is order-independent, but the parity keeps the claim above honest).
READ_MEMBER: tuple[str, ...] = (ROLE_GUEST, ROLE_OWNER, ROLE_ADMIN)
"""Any workspace member may read internal (non-public) workspace data."""


@dataclass(frozen=True)
class Decision:
    """Outcome of an authorization check. Truthy iff access is allowed."""

    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


# action ("<resource>:<verb>") -> the role tuple it requires. These mirror the
# allowed_roles lists at today's call sites exactly.
_ROLE_ACTIONS: dict[str, tuple[str, ...]] = {
    # owner-only administration
    "workspace:administer": ADMINISTER,
    "workspace:delete": ADMINISTER,
    "billing:manage": ADMINISTER,
    "member:manage": ADMINISTER,
    # owner + admin management (the dominant capability)
    "workspace:manage": MANAGE,
    "product:create": MANAGE,
    "product:manage": MANAGE,
    "component:create": MANAGE,
    "component:manage": MANAGE,
    "release:manage": MANAGE,
    "sbom:manage": MANAGE,
    "document:manage": MANAGE,
    # artifact upload — also allows OIDC/CI bot identities
    "artifact:publish": PUBLISH,
    # any-member read of internal workspace data
    "workspace:read": READ_MEMBER,
    "component:read_internal": READ_MEMBER,
}

# Actions authorized by resource attributes (visibility / NDA / access request)
# rather than role. Delegated to ``check_component_access``; the resource must be
# a Component or expose ``.component``.
_ABAC_ACTIONS: frozenset[str] = frozenset({"component:access"})


class UnknownActionError(KeyError):
    """Raised when ``can`` is asked about an action that isn't registered."""


def _stub_request_for_user(user: Any) -> HttpRequest:
    """A request carrying just ``user`` and an EMPTY session.

    Mirrors ``check_component_access_for_user``: the empty session makes
    ``verify_item_access`` skip nothing it wouldn't already (the role is read
    from the live DB), and there is no token scope. Use for delegated checks
    that have no authenticated HTTP request to trust.
    """
    stub = HttpRequest()
    stub.user = user
    stub.session = {}  # type: ignore[assignment]
    return stub


def can(actor: Any, action: str, resource: Any) -> Decision:
    """Authorize ``actor`` to perform ``action`` on ``resource``.

    ``actor`` is an ``HttpRequest`` (preserving token-workspace scoping) or a
    ``User`` (a delegated, session-less check against live DB state). ``action``
    is a registered ``"<resource>:<verb>"`` string; an unregistered action
    raises ``UnknownActionError`` so typos fail loudly in development rather than
    silently allowing or denying.

    Delegates to the existing enforcement functions, so the decision matches the
    inline checks it replaces.
    """
    from sbomify.apps.core.services.access_control import check_component_access
    from sbomify.apps.core.utils import verify_item_access

    request = actor if isinstance(actor, HttpRequest) else _stub_request_for_user(actor)

    if action in _ABAC_ACTIONS:
        component = getattr(resource, "component", resource)
        result = check_component_access(request, component)
        return Decision(result.has_access, result.reason)

    roles = _ROLE_ACTIONS.get(action)
    if roles is None:
        raise UnknownActionError(action)
    allowed = verify_item_access(request, resource, list(roles))
    return Decision(allowed, "" if allowed else f"requires role in {roles}")
