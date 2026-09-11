"""Certification badges as a trust-center visitor sees them.

A workspace proves a certification the same way it proves anything else here: by
publishing the artifact. So a badge is not a flag somebody ticks, it is the
projection of a document that is actually there. Three things have to hold at
once, and each one is the answer to a way the badge could lie:

* The document hangs off a **company-wide** component, because a certification
  covers the organization. One product's SOC 2 report is not the company's.
* That component is **published** (public or gated). Gated counts: the trust
  center already shows a gated artifact exists and gates only the download, and
  "we hold this certification, ask us for the report" is exactly what a badge
  is for.
* The document has a **file uploaded**. An empty component named "ISO 27001"
  asserts nothing, and it is the easiest way to accidentally claim a
  certification the workspace does not hold.

An NDA is a compliance document and deliberately gets no badge: signing one is
not an attestation about the workspace's own security.

One badge per certification, newest document first, so a workspace that uploads
every year's report shows one ISO 27001 badge rather than five.
"""

from __future__ import annotations

from typing import Any

from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team

# What a badge says, and which seal it wears. The order here is the order on the
# page: the strongest assurance first, so a reader scanning left to right stops
# at the best thing the workspace has.
#
# image is a static path. They are placeholders drawn from the design tokens
# until the real seals land, which is a file swap and nothing else: nothing
# outside this table names an image.
BADGE_CATALOGUE: dict[str, dict[str, str]] = {
    Document.ComplianceSubcategory.ISO27001: {
        "summary": "Certified information security management.",
        "image": "img/trust-center/badges/iso27001.svg",
    },
    Document.ComplianceSubcategory.SOC2_TYPE2: {
        "summary": "Controls tested over a period by an independent auditor.",
        "image": "img/trust-center/badges/soc2-type2.svg",
    },
    Document.ComplianceSubcategory.SOC2_TYPE1: {
        "summary": "Controls reviewed by an independent auditor at a point in time.",
        "image": "img/trust-center/badges/soc2-type1.svg",
    },
    Document.ComplianceSubcategory.SOC2: {
        "summary": "Independently audited security controls.",
        "image": "img/trust-center/badges/soc2.svg",
    },
}

# Publishing an artifact is what puts it on the trust center at all; the gate is
# on the download, not on the fact that it exists.
_PUBLISHED = (Component.Visibility.PUBLIC, Component.Visibility.GATED)


def public_certification_badges(team: Team) -> list[dict[str, Any]]:
    """Badges this workspace has earned, in catalogue order.

    Args:
        team: The workspace whose trust center is being rendered.

    Returns:
        One entry per certification, each carrying what the badge shows and
        where the artifact behind it lives. Empty when the workspace has
        published no company-wide compliance document with a file on it.
    """
    documents = (
        Document.objects.filter(
            component__team=team,
            component__is_global=True,
            component__visibility__in=_PUBLISHED,
            document_type=Document.DocumentType.COMPLIANCE,
            compliance_subcategory__in=list(BADGE_CATALOGUE),
        )
        .exclude(document_filename="")
        .exclude(document_filename__isnull=True)
        .select_related("component")
        .order_by("-created_at")
    )

    # Newest first out of the query, so the first document of a subcategory to
    # arrive here is the one the badge points at.
    earned: dict[str, dict[str, Any]] = {}
    for document in documents:
        subcategory = document.compliance_subcategory or ""
        if subcategory in earned:
            continue
        earned[subcategory] = {
            "key": subcategory,
            "label": document.get_compliance_badge(),
            "summary": BADGE_CATALOGUE[subcategory]["summary"],
            "image": BADGE_CATALOGUE[subcategory]["image"],
            "component_id": document.component.id,
            "component_slug": document.component.slug,
            "document_name": document.name,
            "version": document.version,
            # The one thing the tile says that is not about the certification
            # itself: whether the reader can open the report straight away.
            "note": (
                "Report available on request" if document.component.visibility == Component.Visibility.GATED else ""
            ),
        }

    return [earned[key] for key in BADGE_CATALOGUE if key in earned]
