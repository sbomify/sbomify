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
    ``services.provision_bot_user_for_binding``) that becomes the
    ``user`` FK on AccessToken rows issued through this binding. That keeps audit logs
    pointing at a stable identity per binding rather than a shared
    workspace-wide bot.

    Account-resurrection guard
    --------------------------

    Once a binding is *pinned*, we match incoming OIDC tokens on GitHub's
    IMMUTABLE numeric IDs, NEVER the mutable ``repository`` string — if a
    GitHub org is deleted and someone re-registers the name, they must
    not be able to take over the binding. Per PyPI's experience with this
    attack surface, the stable identifiers are:

    * ``repository_owner_id`` — the user/org's stable ID
    * ``repository_id`` — the repository's stable ID

    *When* those IDs are pinned depends on what we can read at create time:

    * **Public repo** — resolved from GitHub's REST API
      (``github_api.resolve_repository``) at create time and pinned
      immediately.
    * **Private repo** — sbomify can't read its metadata anonymously, so
      the binding is created UNPINNED (IDs NULL) and the IDs are pinned
      from the first *signed* OIDC token at exchange (the token already
      carries them). Trust-on-first-use: the ``repository`` name binds to
      whoever publishes first, a narrow window between create and first
      publish. After pinning, matching is ID-based like the public case.

    The ``repository`` string is the match key only while UNPINNED; once
    pinned it's display-only and may drift after a rename.
    """

    PROVIDER_GITHUB = "github"
    PROVIDER_CHOICES = [(PROVIDER_GITHUB, "GitHub Actions")]

    id = models.CharField(max_length=20, primary_key=True, default=generate_id, editable=False)
    component = models.ForeignKey("sboms.Component", on_delete=models.CASCADE, related_name="oidc_bindings")
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default=PROVIDER_GITHUB)
    repository = models.CharField(
        max_length=255,
        help_text=(
            "External repository identifier. GitHub: 'org/repo' (case-insensitive, "
            "stored lowercase). Used to match a still-UNPINNED binding on the first "
            "exchange; once the IDs below are pinned, matching is by ID and this "
            "string is display-only (may go stale after a rename)."
        ),
    )
    repository_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text=(
            "GitHub's immutable numeric repository ID. NULL until pinned. Resolved "
            "at create time for public repos; for private repos (sbomify can't read "
            "their metadata anonymously) it stays NULL and is pinned from the first "
            "signed OIDC token at exchange. Once set, the exchange matches on this, "
            "NEVER the name."
        ),
    )
    repository_owner_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text=(
            "GitHub's immutable numeric owner (user/org) ID. NULL until pinned "
            "(see ``repository_id``). Matched alongside ``repository_id`` to defeat "
            "account-resurrection attacks."
        ),
    )
    bot_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oidc_binding",
        null=True,
        help_text=(
            "Synthetic bot identity for this binding. Created in the same "
            "transaction as the binding via ``services.provision_bot_user_for_binding``. "
            "Cleanup is asymmetric: ``on_delete=CASCADE`` runs when the User is "
            "deleted (it removes this binding row), NOT when the binding is "
            "deleted — for binding → bot cleanup we rely on the "
            "``cleanup_bot_user_on_binding_delete`` post_delete signal in "
            "``signals.py``. Nullable solely to support the two-phase create "
            "flow in ``services.create_binding``: the binding is INSERTed "
            "first to get a stable ``id`` (used to derive the bot username), "
            "then the bot is provisioned and the FK is attached. Outside "
            "that ~µs window inside the create transaction the column is "
            "always non-null."
        ),
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
            # Both IDs are pinned together or not at all. Enforce it at the DB
            # so a partial-pin (reachable only via a manual edit / backfill)
            # can't exist — such a row would never match an exchange lookup and
            # would land in the wrong uniqueness branch below. This is also why
            # the conditional constraints below check BOTH columns, not just
            # ``repository_id``.
            models.CheckConstraint(
                condition=(
                    models.Q(repository_id__isnull=True, repository_owner_id__isnull=True)
                    | models.Q(repository_id__isnull=False, repository_owner_id__isnull=False)
                ),
                name="oidc_binding_ids_both_or_neither",
            ),
            # Uniqueness is conditional on pin state, because the natural key
            # changes once a binding is pinned:
            #   * UNPINNED (IDs NULL) — keyed by repo NAME. Stops a second
            #     unpinned binding for the same name slipping in before the
            #     first pins. (A plain NULL-column unique constraint can't do
            #     this — NULLs compare distinct in Postgres.)
            #   * PINNED — keyed by the immutable IDs. Restores per-repo dedup
            #     and, crucially, does NOT key on the mutable ``repository``
            #     string: after a rename the binding keeps its stale name but
            #     must not block someone binding a NEW repo that later reuses
            #     the freed name.
            models.UniqueConstraint(
                fields=["component", "provider", "repository"],
                condition=models.Q(repository_id__isnull=True, repository_owner_id__isnull=True),
                name="oidc_binding_unique_unpinned_repo_name",
            ),
            models.UniqueConstraint(
                fields=["component", "provider", "repository_owner_id", "repository_id"],
                condition=models.Q(repository_id__isnull=False, repository_owner_id__isnull=False),
                name="oidc_binding_unique_pinned_repo_ids",
            ),
        ]
        indexes = [
            # Pinned-exchange hot path: lookup by (provider, repository_owner_id, repository_id).
            models.Index(
                fields=["provider", "repository_owner_id", "repository_id"],
                name="oidc_binding_provider_ids_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.repository} (owner={self.repository_owner_id} repo={self.repository_id})"
