"""Single authorization decision point.

``can(actor, action, resource)`` is the one front door for authorization. It maps
a named ``action`` to a capability tier, then **delegates** to the enforcement
primitives — ``verify_item_access`` (role-based) and ``check_component_access``
(resource-attribute-based).

Authorization is consolidated here: call sites use ``can``, and a ruff
banned-api rule blocks new direct ``verify_item_access`` imports outside the
authz core, so role checks don't scatter again. ``can`` still delegates to
``verify_item_access`` / ``check_component_access`` — it unifies the two, it
doesn't replace them.

``can`` also enforces API-token **action scopes** (#215): when the actor is a
request authenticated by a scoped access token, the action must be in the
token's scopes (a set of action strings) or the decision is denied *before* the
role/ABAC check — scope can only narrow, never widen. An unscoped (``NULL``)
token is full-capability (legacy default).

Finer workspace roles (#468): admins were raised to near-owners — the only
capability they lack is deleting the workspace. Deletion of domain resources,
workspace settings, billing and member management all moved from owner-only to
``ADMINISTER``. The remaining owner-exclusive rule, *an admin may not remove an
owner*, is relational rather than a capability and therefore is NOT expressible
here; it lives in the member-removal guards in ``teams.views``.

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

# Capability tiers: the named role sets every action is granted to. These tuples
# are the ONLY place roles are enumerated — call sites, view ``allowed_roles``
# and template capability flags all derive from them, so widening a tier widens
# every gate that uses it.
#
# Invariant: the human roles form a linear ladder, guest ⊂ admin ⊂ owner. No role
# may hold a capability a more-privileged role lacks. ``bot`` sits outside the
# ladder — it is a synthetic OIDC publishing identity that can publish releases
# without being able to read most internal data. ``test_role_ladder_is_upward_closed``
# enforces the invariant; keeping it is what stops this degenerating into
# per-role permission soup where "what can an admin do" needs a codebase search.
OWNER_ONLY: tuple[str, ...] = (ROLE_OWNER,)
"""Reserved to the workspace owner. Deliberately tiny: deleting the workspace is
the only *capability* an admin lacks. The other owner-exclusive rule — an admin
may not remove an owner — is relational (it depends on the target member's role,
not just the actor's), so it cannot be expressed as a tier and lives in the
member-removal guards instead."""

ADMINISTER: tuple[str, ...] = (ROLE_OWNER, ROLE_ADMIN)
"""Workspace governance: settings, custom domain, trust-center config, branding,
billing, member management, integrations, and visibility changes. Admins are
near-owners; see ``OWNER_ONLY`` for the two things they can't do."""

MANAGE: tuple[str, ...] = (ROLE_OWNER, ROLE_ADMIN)
"""Create/update products, components, releases, and artifact metadata."""

DELETE: tuple[str, ...] = (ROLE_OWNER, ROLE_ADMIN)
"""Deletion of a domain resource (product / component / release / SBOM /
document). Kept as a tier distinct from ``MANAGE`` — deletion policy has moved
twice already, and a named tier makes moving it again a one-line change."""

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


# Human-facing explanation of each role, ordered most- to least-privileged.
# Deliberately kept beside the capability table above: the workspace members page
# is the only place a user ever learns what a role means, so a tier change and
# its explanation have to move together or the UI quietly starts lying.
# ``bot`` is omitted — it is a synthetic OIDC publishing identity, never assigned
# by a human and never shown in role pickers.
ROLE_DESCRIPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        ROLE_OWNER,
        "Owner",
        "Full control of the workspace. Everything an admin can do, plus deleting "
        "the workspace and removing other owners.",
    ),
    (
        ROLE_ADMIN,
        "Admin",
        "Runs the workspace day to day: create, edit and delete products, "
        "components and releases; upload artifacts; manage workspace settings, "
        "the Trust Center, integrations, members and billing. Cannot remove an "
        "owner or delete the workspace.",
    ),
    (
        ROLE_GUEST,
        "Guest",
        "Limited access, granted through the Trust Center rather than invited "
        "directly. Can view workspace data and upload artifacts, but cannot "
        "create or manage products, components, releases or any settings. Also "
        "reaches gated documents they have been approved for and signed the NDA "
        "for.",
    ),
)
# NOTE: keep the guest text above in step with the tiers — guests currently hold
# READ_MEMBER (internal reads) and PUBLISH (artifact upload), which is why it
# does NOT say "external, public content only". #468 narrows guest to a purely
# external trust-center role; this description must be rewritten in the same
# change, or the members page will understate what a guest can reach.


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
    # owner-only
    "workspace:delete": OWNER_ONLY,
    # owner + admin governance
    "workspace:administer": ADMINISTER,
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
    # deletion of domain resources — owner + admin
    "product:delete": DELETE,
    "component:delete": DELETE,
    "release:delete": DELETE,
    "sbom:delete": DELETE,
    "document:delete": DELETE,
    # artifact upload — allows OIDC/CI bot identities and guests (#468)
    "artifact:publish": PUBLISH,
    # VEX publishing rewrites the workspace's stored vulnerability posture (the
    # re-annotated scan summaries feed every dashboard), so guests are excluded;
    # owners, admins and the CI/OIDC bot keep it.
    "artifact:publish_vex": RELEASE_PUBLISH,
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
