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
    """

    PROVIDER_GITHUB = "github"
    PROVIDER_CHOICES = [(PROVIDER_GITHUB, "GitHub Actions")]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    component = models.ForeignKey("sboms.Component", on_delete=models.CASCADE, related_name="oidc_bindings")
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default=PROVIDER_GITHUB)
    repository = models.CharField(
        max_length=255,
        help_text="External repository identifier. GitHub: 'org/repo' (case-insensitive, stored lowercase).",
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
                fields=["component", "provider", "repository"],
                name="oidc_binding_unique_per_component_repo",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "repository"], name="oidc_binding_provider_repo_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.repository} → component={self.component_id}"
