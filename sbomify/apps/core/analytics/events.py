"""Single source of truth for PostHog event names and property schemas.

Why a registry
==============

Event names and property schemas were previously string literals
scattered across 18+ call sites in views, signals, webhook handlers,
and background tasks. That made it easy to:

* introduce typos (``team:role_chnaged`` vs ``team:role_changed``)
  that silently produce a new event in PostHog rather than failing fast
* ship inconsistent property names for the "same" semantic (one site
  ships ``team_id``, another ``team_key`` for the same workspace)
* leak PII by adding a property to a capture without going through the
  PII review the original event went through

This module centralises every event the product fires so that:

* every event has one canonical name (referenced via a Python constant
  in code that wants strong static checks)
* every event has a documented description, distinct_id convention
  (workspace / user / system), and property schema
* ``validate_payload`` helper compares a fired payload against the
  schema and returns warnings when they diverge. It is wired into
  ``posthog_service.capture`` to log (never raise) drift in production
  logs as it happens, and the registry tests assert the
  ``SHIPPED_EVENTS`` set matches the registered set so drift surfaces
  in CI too.

The registry deliberately does NOT block unregistered events at
``capture`` time — production analytics should be resilient and
forward-compatible. The intended enforcement is the ``SHIPPED_EVENTS``
test, which fails CI when a new event ships without a registration
entry, plus the runtime warning emitted from ``capture`` for property
drift.

Distinct_id convention
======================

Per PR #822 / the Tier 1+2 conventions, the distinct_id for each event
depends on its scope:

* ``"workspace"`` — the canonical Tier 2 default. ``distinct_id`` is
  the workspace key; ``groups={"workspace": workspace_key}``. Used for
  events about workspace-level activity (member invited, branding
  changed, custom domain added, SBOM uploaded, etc.) so PostHog
  attributes activity to the workspace rather than the individual
  user.
* ``"user"`` — for genuinely user-scoped events that don't belong to a
  workspace (``user:account_deleted`` after the user has soft-deleted,
  ``billing:enterprise_contact_submitted`` from a visitor with no
  workspace). ``distinct_id`` is the user PK or session-derived.
  Note: ``user:signed_up`` is intentionally ``"workspace"`` — by the
  time the signal fires we already have the default workspace key
  (the post_save handler creates one), and attributing the signup to
  the workspace keeps the funnel consistent with the rest of Tier 2.
* ``"system"`` — for events fired from background context with no
  workspace (rare). ``distinct_id`` is the literal string ``"system"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sbomify.logging import getLogger

logger = getLogger(__name__)

DistinctIdKind = Literal["workspace", "user", "system"]


@dataclass(frozen=True)
class EventSpec:
    """Schema for a single PostHog event."""

    name: str
    description: str
    distinct_id_kind: DistinctIdKind
    properties: dict[str, str] = field(default_factory=dict)
    """Mapping of property name to a one-line description."""

    pii_notes: str = ""
    """Free-text notes about PII handling for this event.

    Use when properties intentionally include or intentionally exclude
    something sensitive, so future maintainers don't accidentally
    "improve" the payload by adding the excluded thing back.
    """


_REGISTRY: dict[str, EventSpec] = {}


def _register(spec: EventSpec) -> str:
    """Register a spec; returns the event NAME string.

    Returning the name (not the spec) lets call sites use the module
    constants directly as the second argument to ``capture()``:

        capture(distinct_id, events.TEAM_MEMBER_INVITED, properties)

    To inspect schema for a registered event, use ``get_spec(name)``.
    Raises ``ValueError`` on duplicate name to catch copy/paste mistakes.
    """
    if spec.name in _REGISTRY:
        raise ValueError(f"Duplicate event registration: {spec.name!r}")
    _REGISTRY[spec.name] = spec
    return spec.name


def get_spec(event_name: str) -> EventSpec | None:
    """Return the registered spec for ``event_name`` or ``None``."""
    return _REGISTRY.get(event_name)


def all_events() -> list[EventSpec]:
    """Return every registered spec, sorted by name. Useful for tests + docs."""
    return sorted(_REGISTRY.values(), key=lambda s: s.name)


def validate_payload(event_name: str, properties: dict[str, object] | None) -> list[str]:
    """Compare a fired payload against the registered schema.

    Returns a list of human-readable warnings (empty when the payload
    matches). Never raises — this is observation, not enforcement, so a
    drift in production doesn't drop events. Tests can assert that
    ``validate_payload`` returns ``[]`` to catch drift before it ships.
    """
    spec = _REGISTRY.get(event_name)
    if spec is None:
        return [f"event {event_name!r} is not in the registry — add it to events.py"]

    warnings: list[str] = []
    actual_props = set((properties or {}).keys())
    expected_props = set(spec.properties.keys())

    unexpected = actual_props - expected_props
    if unexpected:
        warnings.append(
            f"event {event_name!r} fired with unexpected properties: {sorted(unexpected)} "
            f"(expected: {sorted(expected_props) or 'none'})"
        )

    # We intentionally do NOT warn on missing properties — most call sites
    # legitimately omit properties they don't have (e.g. anonymous flows
    # without team_key). Required-property semantics belong on the producer
    # side; the registry just documents the maximum schema.

    return warnings


# =============================================================================
# Event definitions
# =============================================================================
#
# Each ``_register(...)`` call returns the event NAME (a str), so the
# constants below are plain strings usable directly as the second
# argument to ``capture(distinct_id, EVENT_NAME, properties)``. To get
# the registered ``EventSpec`` for schema introspection, call
# ``get_spec(name)``.
#
# Existing call sites continue to pass string literals — switching them
# over to use these constants is mechanical churn deferred to a
# follow-up. New captures SHOULD use the constants so a typo is a
# NameError at import time rather than a silent new event in PostHog.

# --- Team events --------------------------------------------------------------

TEAM_MEMBER_INVITED = _register(
    EventSpec(
        name="team:member_invited",
        description="An admin/owner invited a new member to a workspace.",
        distinct_id_kind="workspace",
        properties={
            "role": "Invited role (owner/admin/guest).",
            "invited_email_domain": "Domain part of the invitee's email; the local-part is never shipped.",
        },
        pii_notes=(
            "Email LOCAL-PART is intentionally excluded — domain alone is the B2B "
            "cohort signal we want. See teams/views/__init__.py for the redaction logic."
        ),
    )
)

TEAM_MEMBER_INVITATION_ACCEPTED = _register(
    EventSpec(
        name="team:member_invitation_accepted",
        description="A user accepted an invitation and was added as a workspace member.",
        distinct_id_kind="workspace",
        properties={"role": "Role the user joined as."},
    )
)

TEAM_MEMBER_REMOVED = _register(
    EventSpec(
        name="team:member_removed",
        description="A workspace member was removed (by admin or self).",
        distinct_id_kind="workspace",
        properties={
            "role": "Role the removed member held.",
            "self_removal": "True when the user removed themselves, False when removed by an admin.",
        },
    )
)

TEAM_ROLE_CHANGED = _register(
    EventSpec(
        name="team:role_changed",
        description="An existing member's role transitioned to a different role.",
        distinct_id_kind="workspace",
        properties={
            "from_role": "Previous role.",
            "to_role": "New role after the transition.",
        },
        pii_notes="Fires only on actual transitions, not no-op saves; see teams/signals/handlers.py.",
    )
)

TEAM_BRANDING_UPDATED = _register(
    EventSpec(
        name="team:branding_updated",
        description="Workspace branding (colours, logo, icon) was updated.",
        distinct_id_kind="workspace",
    )
)

TEAM_CUSTOM_DOMAIN_ADDED = _register(
    EventSpec(
        name="team:custom_domain_added",
        description="A workspace set its first custom domain.",
        distinct_id_kind="workspace",
        pii_notes=(
            "Fires only on first-time set, not on domain CHANGE; see teams/apis.py "
            "is_first_time_set gate. The domain string itself is intentionally not "
            "shipped — it's user-chosen and could leak customer identity."
        ),
    )
)

# --- API token events ---------------------------------------------------------

API_TOKEN_CREATED = _register(
    EventSpec(
        name="api_token:created",
        description="A user created a personal access token scoped to a workspace.",
        distinct_id_kind="workspace",
        pii_notes=(
            "Token description (user-supplied free text) is intentionally NOT "
            "shipped — it may contain customer names or copied secrets. The event "
            "fire itself is the signal."
        ),
    )
)

API_TOKEN_DELETED = _register(
    EventSpec(
        name="api_token:deleted",
        description="A personal access token was revoked.",
        distinct_id_kind="workspace",
    )
)

# --- Product / Component / Release events -------------------------------------

PRODUCT_CREATED = _register(
    EventSpec(
        name="product:created",
        description="A new product was created in a workspace.",
        distinct_id_kind="workspace",
        properties={
            "product_id": "The created product's ID.",
            "is_public": "Whether the product is publicly visible.",
        },
    )
)

COMPONENT_CREATED = _register(
    EventSpec(
        name="component:created",
        description="A new component was created in a workspace.",
        distinct_id_kind="workspace",
        properties={
            "component_id": "The created component's ID.",
            "component_type": "Component type classifier.",
            "visibility": "One of 'public' / 'private' / 'gated' — the ComponentVisibility enum value.",
        },
    )
)

COMPONENT_FIRST_CREATED = _register(
    EventSpec(
        name="component:first_created",
        description="A workspace owner created their first component (onboarding signal).",
        distinct_id_kind="workspace",
        properties={"component_id": "The first component's ID."},
    )
)

RELEASE_CREATED = _register(
    EventSpec(
        name="release:created",
        description="A new release was tagged on a product.",
        distinct_id_kind="workspace",
        properties={
            "release_id": "The created release's ID.",
            "product_id": "Owning product's ID.",
            "is_prerelease": "Whether this release is flagged as a pre-release.",
        },
    )
)

ITEM_VISIBILITY_TOGGLED = _register(
    EventSpec(
        name="item:visibility_toggled",
        description="A product or component's visibility was toggled.",
        distinct_id_kind="workspace",
        properties={
            "item_type": "'product' or 'component'.",
            "item_id": "Affected item's ID.",
            "new_visibility": (
                "Visibility after the toggle. Products: 'public' or 'private'. "
                "Components: 'public', 'private', or 'gated' (trust-center NDA-gated access)."
            ),
        },
    )
)

# --- SBOM / document events ---------------------------------------------------

SBOM_UPLOADED = _register(
    EventSpec(
        name="sbom:uploaded",
        description="An SBOM artifact was uploaded to a component (Tier 1 retention signal).",
        distinct_id_kind="workspace",
        properties={
            "component_id": "Owning component's ID.",
            "sbom_id": "Uploaded SBOM's ID.",
            "source": "How it arrived: 'api', 'manual_upload', or another stored source tag.",
        },
    )
)

SBOM_DOWNLOADED = _register(
    EventSpec(
        name="sbom:downloaded",
        description="An SBOM artifact was downloaded.",
        distinct_id_kind="user",
        properties={
            "sbom_id": "Downloaded SBOM's ID.",
            "component_id": "Owning component's ID.",
        },
    )
)

# VEX/CBOM/HBOM rows live in the SBOM table (bom_type discriminates), so their
# lifecycle events mirror the SBOM ones but ship under their own names — a VEX
# upload or an in-app triage save must not read as an SBOM upload in funnels.

VEX_UPLOADED = _register(
    EventSpec(
        name="vex:uploaded",
        description=(
            "A VEX artifact was stored on a component — an import, a Dependency-Track "
            "triage sync, or an in-app triage save (the source property tells them apart)."
        ),
        distinct_id_kind="workspace",
        properties={
            "component_id": "Owning component's ID.",
            "sbom_id": "Stored VEX artifact row's ID (VEX rows live in the SBOM table).",
            "source": "'api', 'manual_upload', 'dependency-track', or 'sbomify-triage'.",
        },
    )
)

CBOM_UPLOADED = _register(
    EventSpec(
        name="cbom:uploaded",
        description="A CBOM (Cryptography BOM) artifact was uploaded to a component.",
        distinct_id_kind="workspace",
        properties={
            "component_id": "Owning component's ID.",
            "sbom_id": "Stored CBOM artifact row's ID (CBOM rows live in the SBOM table).",
            "source": "How it arrived: 'api', 'manual_upload', or another stored source tag.",
        },
    )
)

HBOM_UPLOADED = _register(
    EventSpec(
        name="hbom:uploaded",
        description="An HBOM (Hardware BOM) artifact was uploaded to a component.",
        distinct_id_kind="workspace",
        properties={
            "component_id": "Owning component's ID.",
            "sbom_id": "Stored HBOM artifact row's ID (HBOM rows live in the SBOM table).",
            "source": "How it arrived: 'api', 'manual_upload', or another stored source tag.",
        },
    )
)

VEX_DOWNLOADED = _register(
    EventSpec(
        name="vex:downloaded",
        description="A stored VEX artifact was downloaded.",
        distinct_id_kind="user",
        properties={
            "sbom_id": "Downloaded VEX artifact row's ID.",
            "component_id": "Owning component's ID.",
        },
    )
)

CBOM_DOWNLOADED = _register(
    EventSpec(
        name="cbom:downloaded",
        description="A stored CBOM artifact was downloaded.",
        distinct_id_kind="user",
        properties={
            "sbom_id": "Downloaded CBOM artifact row's ID.",
            "component_id": "Owning component's ID.",
        },
    )
)

HBOM_DOWNLOADED = _register(
    EventSpec(
        name="hbom:downloaded",
        description="A stored HBOM artifact was downloaded.",
        distinct_id_kind="user",
        properties={
            "sbom_id": "Downloaded HBOM artifact row's ID.",
            "component_id": "Owning component's ID.",
        },
    )
)

SBOM_DELETED = _register(
    EventSpec(
        name="sbom:deleted",
        description="An SBOM artifact was deleted from a component.",
        distinct_id_kind="workspace",
        properties={
            "component_id": "Owning component's ID.",
            "sbom_id": "Deleted SBOM's ID.",
            "source": "How the artifact had arrived (its stored source tag).",
        },
    )
)

VEX_DELETED = _register(
    EventSpec(
        name="vex:deleted",
        description="A VEX artifact was deleted from a component (retracts its suppressions).",
        distinct_id_kind="workspace",
        properties={
            "component_id": "Owning component's ID.",
            "sbom_id": "Deleted VEX artifact row's ID.",
            "source": "How the artifact had arrived (its stored source tag).",
        },
    )
)

CBOM_DELETED = _register(
    EventSpec(
        name="cbom:deleted",
        description="A CBOM artifact was deleted from a component.",
        distinct_id_kind="workspace",
        properties={
            "component_id": "Owning component's ID.",
            "sbom_id": "Deleted CBOM artifact row's ID.",
            "source": "How the artifact had arrived (its stored source tag).",
        },
    )
)

HBOM_DELETED = _register(
    EventSpec(
        name="hbom:deleted",
        description="An HBOM artifact was deleted from a component.",
        distinct_id_kind="workspace",
        properties={
            "component_id": "Owning component's ID.",
            "sbom_id": "Deleted HBOM artifact row's ID.",
            "source": "How the artifact had arrived (its stored source tag).",
        },
    )
)

RELEASE_SBOM_DOWNLOADED = _register(
    EventSpec(
        name="release_sbom:downloaded",
        description="The merged release-level SBOM was downloaded (Trust Center or API).",
        distinct_id_kind="workspace",
        properties={
            "release_id": "The release's ID.",
            "product_id": "Owning product's ID.",
            "format": "Requested output format: 'cyclonedx' or 'spdx'.",
        },
    )
)

RELEASE_VEX_DOWNLOADED = _register(
    EventSpec(
        name="release_vex:downloaded",
        description="The merged release-level VEX was downloaded (Trust Center or API).",
        distinct_id_kind="workspace",
        properties={
            "release_id": "The release's ID.",
            "product_id": "Owning product's ID.",
        },
    )
)

RELEASE_CBOM_DOWNLOADED = _register(
    EventSpec(
        name="release_cbom:downloaded",
        description="The merged release-level CBOM was downloaded (Trust Center or API).",
        distinct_id_kind="workspace",
        properties={
            "release_id": "The release's ID.",
            "product_id": "Owning product's ID.",
        },
    )
)

DOCUMENT_UPLOADED = _register(
    EventSpec(
        name="document:uploaded",
        description="A document artifact was uploaded to a component (Tier 1 retention signal).",
        distinct_id_kind="workspace",
        properties={
            "component_id": "Owning component's ID.",
            "document_id": "Uploaded document's ID.",
        },
    )
)

BOM_ARTIFACT_FIRST_UPLOADED = _register(
    EventSpec(
        name="bom_artifact:first_uploaded",
        description="A workspace got its first BOM artifact (onboarding signal).",
        distinct_id_kind="workspace",
        properties={"component_id": "Owning component's ID."},
    )
)

# --- Trust-center / access-request events -------------------------------------

DOCUMENT_ACCESS_REQUESTED = _register(
    EventSpec(
        name="document:access_requested",
        description="A user requested access to a workspace's trust-center documents.",
        distinct_id_kind="workspace",
        properties={"requires_nda": "Whether the workspace requires NDA signing for access."},
    )
)

DOCUMENT_ACCESS_APPROVED = _register(
    EventSpec(
        name="document:access_approved",
        description="An admin approved a pending access request.",
        distinct_id_kind="workspace",
    )
)

DOCUMENT_ACCESS_DENIED = _register(
    EventSpec(
        name="document:access_denied",
        description="An admin rejected a pending access request.",
        distinct_id_kind="workspace",
    )
)

NDA_SIGNED = _register(
    EventSpec(
        name="nda:signed",
        description="A user signed the workspace's NDA as part of the access flow.",
        distinct_id_kind="workspace",
    )
)

# --- Search / discovery events ------------------------------------------------

SEARCH_PERFORMED = _register(
    EventSpec(
        name="search:performed",
        description="A user ran a search in the dashboard.",
        distinct_id_kind="workspace",
        properties={
            "query_length": "Character length of the query string.",
            "result_count": "Number of results returned (products + components).",
        },
        pii_notes=(
            "The raw query string is NEVER shipped — it can contain customer "
            "identifiers, internal component names, or secrets pasted by accident. "
            "See core/views/search.py for the comment guard."
        ),
    )
)

# --- User lifecycle events ----------------------------------------------------

USER_SIGNED_UP = _register(
    EventSpec(
        name="user:signed_up",
        description="A new user signed up.",
        distinct_id_kind="workspace",
        properties={"signup_method": "Auth provider used (e.g. 'keycloak')."},
    )
)

USER_ACCOUNT_DELETED = _register(
    EventSpec(
        name="user:account_deleted",
        description="A user soft-deleted their account.",
        distinct_id_kind="user",
    )
)

# --- Onboarding events --------------------------------------------------------

ONBOARDING_WIZARD_COMPLETED = _register(
    EventSpec(
        name="onboarding:wizard_completed",
        description="A workspace owner completed the onboarding wizard.",
        distinct_id_kind="workspace",
    )
)

# --- Billing events -----------------------------------------------------------

BILLING_TRIAL_EXPIRED = _register(
    EventSpec(
        name="billing:trial_expired",
        description="A workspace's trial period ended and they were downgraded to community.",
        distinct_id_kind="workspace",
        properties={"team_key": "Workspace key (redundant with distinct_id; kept for legacy)."},
        pii_notes="Fires exactly once per team via TrialExpiryEmissionGuard's two-marker state machine.",
    )
)

BILLING_SUBSCRIPTION_UPDATED = _register(
    EventSpec(
        name="billing:subscription_updated",
        description="A Stripe subscription update was processed.",
        distinct_id_kind="workspace",
    )
)

BILLING_SUBSCRIPTION_CANCELED = _register(
    EventSpec(
        name="billing:subscription_canceled",
        description="A Stripe subscription ended.",
        distinct_id_kind="workspace",
    )
)

BILLING_PAYMENT_FAILED = _register(
    EventSpec(
        name="billing:payment_failed",
        description="A Stripe invoice payment failed.",
        distinct_id_kind="workspace",
    )
)

BILLING_PAYMENT_SUCCEEDED = _register(
    EventSpec(
        name="billing:payment_succeeded",
        description="A Stripe invoice payment succeeded.",
        distinct_id_kind="workspace",
    )
)

BILLING_CHECKOUT_COMPLETED = _register(
    EventSpec(
        name="billing:checkout_completed",
        description="A Stripe checkout session completed successfully.",
        distinct_id_kind="workspace",
    )
)

BILLING_ENTERPRISE_CONTACT_SUBMITTED = _register(
    EventSpec(
        name="billing:enterprise_contact_submitted",
        description="A visitor submitted the enterprise contact form.",
        distinct_id_kind="user",
        properties={"company_size": "Self-reported company size bucket."},
    )
)

# --- Vulnerability scanning events --------------------------------------------

VULNERABILITY_SCAN_INITIATED = _register(
    EventSpec(
        name="vulnerability_scan:initiated",
        description="A vulnerability scan was dispatched to a worker for an SBOM.",
        distinct_id_kind="workspace",
        properties={
            "sbom_id": "Target SBOM's ID.",
            "plugin": "Plugin selected for the scan.",
            "reason": "Why the scan was triggered (upload / manual / scheduled / etc.).",
        },
    )
)

VULNERABILITY_SCAN_COMPLETED = _register(
    EventSpec(
        name="vulnerability_scan:completed",
        description="A vulnerability scan completed (success or failure) for an SBOM.",
        distinct_id_kind="workspace",
        properties={
            "sbom_id": "Scanned SBOM's ID.",
            "plugin": "Plugin that ran the scan.",
            "status": "Final assessment status (completed / failed / etc.).",
        },
    )
)
