"""The populations every ops metric counts over.

The old admin dashboard was wrong mostly because it never said what it was
counting. "Total Users" included accounts pending deletion and synthetic
publishing identities; "Users per Workspace" counted the same bots; the
onboarding funnel divided one population by another. Each of those reads as a
plausible ORM call and none of them is the number anyone wanted.

So the populations live here, once, with their reasoning attached, and the
panels compose them. If a definition is wrong it is wrong in one place and one
test.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q, QuerySet

from sbomify.apps.core.models import User
from sbomify.apps.documents.models import Document
from sbomify.apps.oidc.services import BOT_USERNAME_PREFIX
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team

BOT_EMAIL_DOMAIN = "sbomify.local"
"""Non-routable domain used for synthetic OIDC identities (RFC 6761 6.3)."""

_IS_BOT = Q(username__startswith=BOT_USERNAME_PREFIX) | Q(email__iendswith=f"@{BOT_EMAIL_DOMAIN}")
"""Mirrors ``oidc.services.is_synthetic_bot_user`` as a queryset predicate.

Matched on the identity convention rather than ``Member.role="bot"`` for the
same reason the function does: a bot User exists before its Member row.
"""


def people() -> QuerySet[User]:
    """Users who are actual people with a live account.

    Excludes three populations the raw ``User`` table carries:

    * Soft-deleted accounts. ``deleted_at`` is set the moment someone asks to
      be deleted, but the row survives until the purge cron runs, up to
      SOFT_DELETE_GRACE_DAYS later. Counting them reports departed users as
      current ones for a fortnight.
    * Deactivated accounts, which are a *separate* state from soft-deleted and
      not a subset of it. The Keycloak ``DELETE_ACCOUNT`` webhook sets only
      ``is_active=False`` and never touches ``deleted_at`` (see
      ``core.views.keycloak_webhook``), so filtering on ``deleted_at`` alone
      keeps every Keycloak-side deletion in the counts permanently.
    * Synthetic OIDC bot identities, which are publishing credentials wearing
      a User row. They can never sign in, so they also permanently inflate any
      "never logged in" count.
    """
    return User.objects.filter(deleted_at__isnull=True, is_active=True).exclude(_IS_BOT)


def bot_identities() -> QuerySet[User]:
    """Synthetic OIDC publishing identities, counted on their own terms."""
    return User.objects.filter(_IS_BOT)


def workspaces() -> QuerySet[Team]:
    """Every workspace.

    Deliberately unfiltered. sbomify's own internal workspaces are in here and
    there is no flag that marks them, so anything using this as a denominator
    is slightly generous. Tagging them is worth doing, and is not something
    this module can invent.
    """
    return Team.objects.all()


def boms() -> QuerySet[SBOM]:
    """Every uploaded BOM row, of any ``bom_type``.

    Named BOMs rather than SBOMs because that is what the table holds: CBOMs,
    HBOMs, AI BOMs, VEX documents and more, and the glossary reserves "SBOM"
    for the case where the type is the point. The old dashboard labelled this
    "Total SBOMs".
    """
    return SBOM.objects.all()


def sboms() -> QuerySet[SBOM]:
    """BOMs that really are SBOMs."""
    return SBOM.objects.filter(bom_type=SBOM.BomType.SBOM)


def documents() -> QuerySet[Document]:
    """Every uploaded document.

    Documents are published through their own component type and their own
    API, and a workspace can use sbomify for nothing else. Counting only BOMs
    makes those workspaces invisible in every usage number.
    """
    return Document.objects.all()


def artifact_count(*, since: datetime | None = None) -> int:
    """How many artifacts have been published, optionally since a moment.

    An artifact is a BOM *or* a document. They live in two tables with no
    common parent, so this is a sum of two counts rather than a queryset; a
    caller that needs rows rather than a total should compose ``boms()`` and
    ``documents()`` itself and say which it means.
    """
    bom_rows = boms()
    document_rows = documents()

    if since is not None:
        bom_rows = bom_rows.filter(created_at__gte=since)
        document_rows = document_rows.filter(created_at__gte=since)

    return bom_rows.count() + document_rows.count()


def workspaces_publishing_since(moment: datetime) -> QuerySet[Team]:
    """Workspaces that published an artifact after ``moment``.

    This is the honest reading of "active": something arrived. Measuring
    ``last_login`` instead is what made the old "active users" number
    meaningless, because under SSO with long-lived sessions a daily user can
    go months without a fresh login.

    Either kind of artifact counts, for the same reason ``artifact_count``
    counts both: a documents-only workspace is using the product.
    """
    return (
        workspaces()
        .filter(Q(component__sbom__created_at__gte=moment) | Q(component__document__created_at__gte=moment))
        .distinct()
    )
