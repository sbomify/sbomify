"""Django signals for TEA cache invalidation.

Listens for post_save/post_delete on models that back TEA responses
and invalidates all TEA cache entries for the affected workspace.

Uses string sender references ("app_label.ModelName") to avoid circular imports.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db.models.signals import post_delete, post_save

from sbomify.apps.tea.cache import invalidate_tea_cache
from sbomify.logging import getLogger

log = getLogger(__name__)

# Models whose changes should trigger TEA cache invalidation.
# String references avoid circular imports; validated at test time.
# Both concrete and proxy models are listed because Django signals
# match on the exact sender class — saving via a proxy model won't
# trigger a signal registered on the concrete model.
_INVALIDATION_SENDERS = [
    "sboms.Product",
    "sboms.ProductIdentifier",
    "sboms.Component",
    "sboms.SBOM",
    "sboms.ProductCLEEvent",
    "sboms.ProductCLESupportDefinition",
    "sboms.ComponentCLEEvent",
    "sboms.ComponentCLESupportDefinition",
    "sboms.ReleaseCLEEvent",
    "sboms.ReleaseCLESupportDefinition",
    "sboms.ComponentReleaseCLEEvent",
    "sboms.ComponentReleaseCLESupportDefinition",
    "documents.Document",
    "core.Product",
    "core.Component",
    "core.Release",
    "core.ReleaseArtifact",
    "core.ComponentRelease",
    "core.ComponentReleaseArtifact",
    "teams.Team",
]


def _get_team_key(instance: Any) -> str | None:
    """Resolve team key from various model instances.

    Each model type has a different path to the team:
    - Team: instance.key (direct)
    - Product, Component, ProductIdentifier: instance.team.key
    - SBOM, Document: instance.component.team.key
    - Release: instance.product.team.key
    - ReleaseArtifact: instance.release.product.team.key
    - ComponentReleaseArtifact: instance.component_release.component.team.key
    """
    try:
        # Team model itself
        model_name = type(instance).__name__
        if model_name == "Team":
            return instance.key  # type: ignore[no-any-return]

        # Direct team FK (Product, Component, ProductIdentifier)
        if hasattr(instance, "team_id") and hasattr(instance, "team"):
            return instance.team.key  # type: ignore[no-any-return]

        # SBOM / Document -> component -> team
        if hasattr(instance, "component_id"):
            return instance.component.team.key  # type: ignore[no-any-return]

        # Release -> product -> team
        if hasattr(instance, "product_id"):
            return instance.product.team.key  # type: ignore[no-any-return]

        # ComponentReleaseArtifact -> component_release -> component -> team
        if hasattr(instance, "component_release_id"):
            return instance.component_release.component.team.key  # type: ignore[no-any-return]

        # ReleaseArtifact -> release -> product -> team
        if hasattr(instance, "release_id"):
            return instance.release.product.team.key  # type: ignore[no-any-return]
    except (AttributeError, ObjectDoesNotExist):
        log.warning(
            "Failed to resolve team key for %s (pk=%s) — possible data integrity issue",
            type(instance).__name__,
            getattr(instance, "pk", "unknown"),
        )
        return None

    log.warning(
        "No team resolution path for %s (pk=%s) — TEA cache invalidation skipped",
        type(instance).__name__,
        getattr(instance, "pk", "unknown"),
    )
    return None


def _invalidate_handler(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Generic handler: resolve team key and invalidate TEA cache."""
    team_key = _get_team_key(instance)
    if team_key:
        invalidate_tea_cache(team_key)


# Register signals for all models using loop pattern.
# dispatch_uid prevents duplicate registration in dev autoreloader / test setups.
for _sender in _INVALIDATION_SENDERS:
    post_save.connect(_invalidate_handler, sender=_sender, dispatch_uid=f"tea_invalidate_save_{_sender}")
    post_delete.connect(_invalidate_handler, sender=_sender, dispatch_uid=f"tea_invalidate_delete_{_sender}")
