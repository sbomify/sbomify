"""OIDC Trusted Publishing models.

Mirrors the PyPI Trusted Publishers pattern: a Component owner registers
a binding that says "GitHub repository ``org/repo`` may upload to this
component". An OIDC token presented by that repository's workflow is
exchanged for a short-lived sbomify access token scoped to the bound
component.

See ``sbomify.apps.oidc.utils`` for the GitHub OIDC verification logic
and ``sbomify.apps.oidc.apis`` for the token-exchange endpoint.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from sbomify.apps.core.utils import generate_id


class OIDCBinding(models.Model):
    """A trust binding from an external OIDC issuer to a Component.

    Each binding owns a synthetic ``bot_user`` (created via
    ``utils.provision_bot_user``) that becomes the ``user`` FK on
    AccessToken rows issued through this binding. That keeps audit logs
    pointing at a stable identity per binding rather than a shared
    workspace-wide bot.

    Account-resurrection guard
    --------------------------

    We MUST NOT match incoming OIDC tokens on the mutable
    ``repository`` (``"org/repo"``) string alone — if a GitHub
    organisation is deleted and someone else registers the same name,
    they'd be able to mint tokens claiming the original repository and
    take over a binding. Per PyPI's experience with this exact attack
    surface, the right identifiers are GitHub's IMMUTABLE numeric IDs:

    * ``repository_owner_id`` — the user/org's stable ID
    * ``repository_id`` — the repository's stable ID

    These are pinned at binding-create time (resolved from GitHub's
    REST API in ``github_api.resolve_repository``) and matched on
    every token exchange. The ``repository`` / ``repository_owner``
    strings are kept for display only; they may drift if the
    repository is renamed but the binding stays valid because the IDs
    still match.
    """

    PROVIDER_GITHUB = "github"
    PROVIDER_CHOICES = [(PROVIDER_GITHUB, "GitHub Actions")]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    component = models.ForeignKey("sboms.Component", on_delete=models.CASCADE, related_name="oidc_bindings")
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default=PROVIDER_GITHUB)
    repository = models.CharField(
        max_length=255,
        help_text=(
            "External repository identifier for DISPLAY only. GitHub: 'org/repo' "
            "(case-insensitive, stored lowercase). Matching uses the immutable "
            "IDs below; this string may go stale after a rename."
        ),
    )
    repository_id = models.BigIntegerField(
        help_text=(
            "GitHub's immutable numeric repository ID. The token-exchange "
            "endpoint matches incoming tokens against this, NEVER the name."
        ),
    )
    repository_owner_id = models.BigIntegerField(
        help_text=(
            "GitHub's immutable numeric owner (user/org) ID. Matched alongside "
            "``repository_id`` to defeat account-resurrection attacks."
        ),
    )
    bot_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oidc_binding",
        help_text="Synthetic bot identity for this binding. Created on save, deleted via CASCADE.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        help_text="The Workspace member who set up this binding (audit).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Updated each time a token is issued. Lets admins prune stale bindings.",
    )

    class Meta:
        db_table = "oidc_bindings"
        constraints = [
            models.UniqueConstraint(
                fields=["component", "provider", "repository_owner_id", "repository_id"],
                name="oidc_binding_unique_per_component_repo_ids",
            ),
        ]
        indexes = [
            # Token-exchange hot-path lookup is by (provider, repository_owner_id, repository_id)
            models.Index(
                fields=["provider", "repository_owner_id", "repository_id"],
                name="oidc_binding_provider_ids_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.repository} (owner={self.repository_owner_id} repo={self.repository_id})"
