"""Single authorization decision point.

``can(actor, action, resource)`` is the one front door for authorization. It maps
a named ``action`` to the capability the codebase already enforces, then
**delegates** to the existing checks — ``verify_item_access`` (role-based) and
``check_component_access`` (resource-attribute-based) — so its decision is
identical to the scattered inline role checks it is meant to replace.

Authorization is consolidated here with no behaviour change to role checks: the
call sites use ``can``, and a ruff banned-api rule blocks new direct
``verify_item_access`` imports outside the authz core, so role checks don't
scatter again. ``can`` still delegates to ``verify_item_access`` /
``check_component_access`` — it unifies the two, it doesn't replace them.

``can`` also enforces API-token **action scopes** (#215): when the actor is a
request authenticated by a scoped access token, the action must be in the
token's scopes (a set of action strings) or the decision is denied *before* the
role/ABAC check — scope can only narrow, never widen. An unscoped (``NULL``)
token is full-capability (legacy default). Growing finer workspace roles (#468)
is the remaining future work.

Why a facade instead of a rewrite: every inline check passed a raw role list
(``["owner", "admin"]``) to ``verify_item_access``. Naming the role sets as
capabilities and giving each action one definition turns "what can an admin do"
from an emergent property of the call sites into a single table here.
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
"""Create/update products, components, releases, and artifact metadata (admins
included). Destructive *deletion* of a domain resource is the separate, stricter
``DELETE`` tier (#468)."""

DELETE: tuple[str, ...] = (ROLE_OWNER,)
"""Owner-only deletion of a domain resource (product / component / release /
SBOM / document). Carved out of ``MANAGE`` so admins can create and edit but not
destroy (#468)."""

PUBLISH: tuple[str, ...] = (ROLE_OWNER, ROLE_ADMIN, ROLE_BOT, ROLE_GUEST)
"""Upload artifacts — granted to OIDC/CI ``bot`` identities and, per #468, to
guests (so a low-trust member can contribute artifacts without management
rights)."""

RELEASE_PUBLISH: tuple[str, ...] = (ROLE_OWNER, ROLE_ADMIN, ROLE_BOT)
"""Cut and tag a release — the release half of the CI publish workflow. Granted
to OIDC/CI ``bot`` identities (the action creates a release and tags its uploaded
artifacts to it) alongside owners and admins. Guests are excluded: they may
contribute artifacts (``PUBLISH``) but not cut releases. Renaming or deleting a
release stays the stricter ``MANAGE`` / ``DELETE`` tiers."""

# Order mirrors the predominant call-site literal ``["guest", "owner", "admin"]``
# (membership is order-independent, but the parity keeps the claim above honest).
READ_MEMBER: tuple[str, ...] = (ROLE_GUEST, ROLE_OWNER, ROLE_ADMIN)
"""Any workspace member may read internal (non-public) workspace data."""

READ_MEMBER_OR_BOT: tuple[str, ...] = (ROLE_GUEST, ROLE_OWNER, ROLE_ADMIN, ROLE_BOT)
"""``READ_MEMBER`` plus the CI/OIDC ``bot``: reading releases is part of the
publish workflow (the action checks whether a release already exists before
creating it), so a bot must reach release reads that other internal reads still
deny it."""


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
    "component:administer": ADMINISTER,
    # owner + admin management (the dominant capability)
    "workspace:manage": MANAGE,
    "product:create": MANAGE,
    "product:manage": MANAGE,
    "component:create": MANAGE,
    "component:manage": MANAGE,
    "release:manage": MANAGE,
    "sbom:manage": MANAGE,
    "document:manage": MANAGE,
    # release publishing — the CI/OIDC bot's job (create a release, tag artifacts
    # to it). Owners and admins keep it; bots gain it; guests stay out.
    "release:create": RELEASE_PUBLISH,
    "release:tag": RELEASE_PUBLISH,
    # owner-only deletion of domain resources (#468) — stricter than MANAGE
    "product:delete": DELETE,
    "component:delete": DELETE,
    "release:delete": DELETE,
    "sbom:delete": DELETE,
    "document:delete": DELETE,
    # artifact upload — allows OIDC/CI bot identities and guests (#468)
    "artifact:publish": PUBLISH,
    # any-member read of internal (non-public) workspace data
    "workspace:read": READ_MEMBER,
    "component:read_internal": READ_MEMBER,
    "product:read": READ_MEMBER,
    "release:read": READ_MEMBER_OR_BOT,
    "document:read": READ_MEMBER,
    "sbom:read": READ_MEMBER,
}

# Actions authorized by resource attributes (visibility / NDA / access request)
# rather than role. Delegated to ``check_component_access``; the resource must be
# a Component or expose ``.component``.
_ABAC_ACTIONS: frozenset[str] = frozenset({"component:access"})

# Every action ``can`` understands — the vocabulary a token scope draws from.
ALL_ACTIONS: frozenset[str] = frozenset(_ROLE_ACTIONS) | _ABAC_ACTIONS
# Resource prefixes (the part before ``:``) — the valid targets of a ``<res>:*`` bundle.
_RESOURCES: frozenset[str] = frozenset(a.split(":", 1)[0] for a in ALL_ACTIONS)

# Token scope grammar (a scope is a set of ``can`` action strings):
#   "*"                 -> every action (full token)
#   "<resource>:*"      -> every verb for that resource
#   "<resource>:<verb>" -> that exact action
SCOPE_WILDCARD = "*"


def is_valid_scope(scope: str) -> bool:
    """True iff ``scope`` is a grammatically valid token scope string."""
    if scope == SCOPE_WILDCARD or scope in ALL_ACTIONS:
        return True
    return scope.endswith(":*") and scope[:-2] in _RESOURCES


# Named scope presets surfaced in the token-creation UI. Each label maps to a
# concrete scope value (``None`` = full / unscoped). Kept here so the UI can't
# drift from the action vocabulary above.
SCOPE_PRESETS: dict[str, list[str] | None] = {
    "full": None,
    # The CI publish workflow the action performs end to end: upload an artifact,
    # then check / create / tag its release. Without the release actions a
    # publish-scoped CI token uploads fine but 403s the moment it cuts a release.
    "publish": ["artifact:publish", "release:read", "release:create", "release:tag"],
    # Every read action (``<resource>:read`` / ``read_internal``) plus the ABAC
    # component:access read path, so a read-only token can still read
    # gated/public components (can() checks scope before ABAC). Keyed on the verb,
    # not a tier identity, so a read action moving to a bot-inclusive tier (e.g.
    # release:read) stays in the read-only preset.
    "read_only": sorted(
        [action for action in _ROLE_ACTIONS if action.split(":", 1)[1].startswith("read")] + list(_ABAC_ACTIONS)
    ),
}


def _scope_permits(scopes: list[str] | None, action: str) -> bool:
    """Does a token's ``scopes`` grant ``action``?

    ``None`` means an unscoped (legacy / full-capability) token — it permits
    everything, matching the ``expires_at IS NULL = never expires`` precedent.
    An empty list permits nothing. Scope can only *narrow* access; the role and
    resource-attribute checks still run afterwards.
    """
    if scopes is None or SCOPE_WILDCARD in scopes:
        return True
    if action in scopes:
        return True
    resource = action.split(":", 1)[0]
    return f"{resource}:*" in scopes


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

    # Validate the action FIRST so a typo raises loudly even for a scoped token —
    # the scope gate below must not be able to mask an unregistered action as a
    # merely-denied Decision.
    if action not in ALL_ACTIONS:
        raise UnknownActionError(action)

    # Token action-scope gate: a scoped API token can only narrow access. Runs
    # before the role/ABAC dispatch so an out-of-scope action is denied even when
    # the user's role would allow it. Non-token actors (sessions, delegated
    # user-stub checks) carry no access_token_record, so this is a no-op for them.
    token = getattr(request, "access_token_record", None)
    if token is not None and not _scope_permits(token.scopes, action):
        return Decision(False, f"token scope does not grant {action!r}")

    if action in _ABAC_ACTIONS:
        component = getattr(resource, "component", resource)
        result = check_component_access(request, component)
        return Decision(result.has_access, result.reason)

    roles = _ROLE_ACTIONS[action]  # present: validated against ALL_ACTIONS above
    allowed = verify_item_access(request, resource, list(roles))
    return Decision(allowed, "" if allowed else f"requires role in {roles}")
