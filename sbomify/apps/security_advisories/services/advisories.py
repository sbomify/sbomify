"""Reading advisories for the workspace UI.

The views render a projection rather than model instances, because the list and
detail pages want a few derived things the model deliberately does not store:
the display id, the worst severity across an advisory's vulnerabilities, and a
timeline that merges messages with status changes.

Everything here is read-only. Writes land with the CRUD pass.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Prefetch, Q, QuerySet

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryReference,
    AdvisoryVulnerability,
    ReferenceType,
    SecurityAdvisory,
)

# Severity to the badge variant the templates use.
SEVERITY_VARIANTS = {
    "critical": "danger",
    "high": "warning",
    "medium": "info",
    "low": "secondary",
}
SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# Remediation status to badge variant and icon. One dict so the list, the detail
# header and the timeline cannot drift apart on how a state looks.
#
# All five are soft-tint variants. tw-badge-accent is the one badge in the
# system with white text, a gradient and a glow, which made fix_in_progress the
# only saturated thing on a page of pale pills. violet keeps the purple the
# design intended and sits between investigating's blue and resolved's green,
# which is also where it belongs in the lifecycle; primary would have been too
# close to info to tell apart a row later.
REMEDIATION_META: dict[str, dict[str, str]] = {
    "identified": {"label": "Identified", "variant": "warning", "icon": "fas fa-circle-exclamation"},
    "investigating": {"label": "Investigating", "variant": "info", "icon": "fas fa-magnifying-glass"},
    "fix_in_progress": {"label": "Fix in progress", "variant": "violet", "icon": "fas fa-wrench"},
    "resolved": {"label": "Resolved", "variant": "success", "icon": "fas fa-circle-check"},
    "wont_fix": {"label": "Won't fix", "variant": "secondary", "icon": "fas fa-ban"},
}
REMEDIATION_RANK = {"identified": 1, "investigating": 2, "fix_in_progress": 3, "resolved": 4, "wont_fix": 5}

# Publication status to badge variant, the second axis on the list.
PUBLICATION_VARIANTS = {"draft": "secondary", "published": "success", "withdrawn": "warning"}

# Advisory "type" as the list column shows it. Inferred rather than stored,
# because the model already records the real identifiers and which database
# issued them is a fact about those, not a separate field to keep in step.
TYPE_LABELS = {"cve": "CVE", "ghsa": "GHSA", "other": "Other"}

# Timeline entries a reader sees. Internal comments are excluded from the
# public feed by the model's PUBLIC_EVENT_TYPES; this is the workspace view, so
# it shows comments too, and marks them.
EVENT_META: dict[str, dict[str, str]] = {
    "comment": {"label": "Comment", "variant": "secondary", "icon": "fas fa-comment"},
    "update": {"label": "Update", "variant": "secondary", "icon": "fas fa-comment-dots"},
    "status_change": {"label": "Status change", "variant": "info", "icon": "fas fa-arrow-right-arrow-left"},
    "field_change": {"label": "Field change", "variant": "secondary", "icon": "fas fa-pen"},
    "visibility_changed": {"label": "Visibility changed", "variant": "secondary", "icon": "fas fa-eye"},
    "published": {"label": "Published", "variant": "success", "icon": "fas fa-bullhorn"},
    "withdrawn": {"label": "Withdrawn", "variant": "warning", "icon": "fas fa-rotate-left"},
    "vulnerability_added": {"label": "Vulnerability added", "variant": "info", "icon": "fas fa-bug"},
    "vulnerability_removed": {"label": "Vulnerability removed", "variant": "secondary", "icon": "fas fa-bug-slash"},
    "product_added": {"label": "Product added", "variant": "info", "icon": "fas fa-cube"},
    "product_removed": {"label": "Product removed", "variant": "secondary", "icon": "fas fa-cube"},
    "cra_early_warning": {"label": "CRA early warning", "variant": "warning", "icon": "fas fa-flag"},
    "cra_notification": {"label": "CRA notification", "variant": "warning", "icon": "fas fa-flag"},
    "cra_final_report": {"label": "CRA final report", "variant": "warning", "icon": "fas fa-flag-checkered"},
    "users_notified": {"label": "Users notified", "variant": "info", "icon": "fas fa-envelope"},
}
_UNKNOWN_EVENT = {"label": "Event", "variant": "secondary", "icon": "fas fa-circle"}


def display_id(advisory: SecurityAdvisory) -> str:
    """The id a human quotes.

    ``tracking_id`` is the workspace's own scheme (OSPN-2026-0034 and the like)
    and is what belongs on screen when set. The generated primary key is the
    fallback, since an advisory is addressable before anyone assigns a tracking
    id.
    """
    return advisory.tracking_id or advisory.id


def _advisory_type(vulnerabilities: list[AdvisoryVulnerability], references: list[AdvisoryReference]) -> str:
    """Which database issued the advisory's identifiers.

    A CVE is the strongest signal and lives on the vulnerability. Anything else
    comes from the references: ``cve_id`` is validated as a real CVE id, so a
    GHSA can only ever arrive as an :class:`AdvisoryReference`, and reading it
    off ``cve_id`` would be a branch that can never fire.
    """
    if any(v.cve_id for v in vulnerabilities):
        return "cve"
    types = {r.reference_type for r in references}
    if ReferenceType.CVE in types:
        return "cve"
    if ReferenceType.GHSA in types:
        return "ghsa"
    return "other"


def display_date(value: Any) -> str:
    """A date the way the list renders it: 19 Jul 2026, no leading zero."""
    if value is None:
        return ""
    return f"{value.day} {value:%b %Y}"


def worst_severity(advisory: SecurityAdvisory) -> str:
    """The advisory's severity, falling back to the worst of its vulnerabilities.

    An advisory carries its own severity, but it is optional, and an advisory
    with three CVEs whose own field is blank should not read as less severe than
    the worst thing in it.
    """
    if advisory.severity:
        return advisory.severity
    severities = [v.severity for v in advisory.vulnerabilities.all() if v.severity]
    if not severities:
        return ""
    return max(severities, key=lambda s: SEVERITY_RANK.get(s, 0))


def _vulnerability_projection(vulnerability: AdvisoryVulnerability) -> dict[str, Any]:
    return {
        "id": vulnerability.id,
        "cve_id": vulnerability.cve_id,
        "title": vulnerability.title,
        "description": vulnerability.description,
        "severity": vulnerability.severity,
        "severity_variant": SEVERITY_VARIANTS.get(vulnerability.severity, "secondary"),
        "cwe_ids": vulnerability.cwe_ids or [],
        "cvss_scores": vulnerability.cvss_scores or [],
        "exploitation_status": vulnerability.exploitation_status,
        "recommendation": vulnerability.recommendation,
    }


def _product_projection(advisory_product: AdvisoryProduct) -> dict[str, Any]:
    """A product chip.

    ``product`` is nullable and ``product_name`` carries the name when the FK is
    absent, so an advisory can name a product this workspace does not track and
    keep naming it after one is deleted. ``id`` is None in that case and the
    template renders plain text rather than a dead link.
    """
    product = advisory_product.product
    name = product.name if product else advisory_product.product_name
    return {
        # A stable non-null key for x-for. ``id`` is null for an unlinked
        # product, and Alpine rejects that as a key, so two unlinked products
        # would also collide on it.
        "key": advisory_product.id,
        "id": product.id if product else None,
        "name": name,
    }


def _reference_projection(reference: AdvisoryReference) -> dict[str, Any]:
    return {
        "id": reference.id,
        "type": reference.reference_type,
        "external_id": reference.external_id,
        "url": reference.url,
        "summary": reference.summary,
        "category": reference.category,
    }


def _event_projection(event: AdvisoryEvent) -> dict[str, Any]:
    meta = EVENT_META.get(event.event_type, _UNKNOWN_EVENT)
    payload = event.payload if isinstance(event.payload, dict) else {}
    actor = event.actor
    return {
        "id": event.id,
        "kind": event.event_type,
        "label": meta["label"],
        "variant": meta["variant"],
        "icon": meta["icon"],
        # "note" and "date_display" are what the timeline template binds to;
        # "body" and "created_at" are the model's own names, kept for callers
        # that want the raw values.
        "note": event.body,
        "date_display": display_date(event.created_at),
        "body": event.body,
        "payload": payload,
        # Only status_change moves the advisory's remediation status; the rest
        # are narrative. The template greys the others accordingly.
        "sets_status": event.event_type == AdvisoryEvent.EventType.STATUS_CHANGE,
        "to_status": payload.get("to"),
        "from_status": payload.get("from"),
        "actor": actor.get_full_name() or actor.username if actor else "",
        "is_internal": event.event_type == AdvisoryEvent.EventType.COMMENT,
        "created_at": event.created_at,
    }


def _advisory_projection(advisory: SecurityAdvisory, *, detail: bool = False) -> dict[str, Any]:
    severity = worst_severity(advisory)
    remediation = REMEDIATION_META.get(advisory.remediation_status, _UNKNOWN_EVENT)
    events = list(advisory.events.all())
    vulnerabilities = list(advisory.vulnerabilities.all())
    references = list(advisory.references.all())
    advisory_type = _advisory_type(vulnerabilities, references)
    updated_at = max((e.created_at for e in events), default=advisory.updated_at)

    projection: dict[str, Any] = {
        # str() because the table's client-side search lowercases this. Both
        # sources are CharFields today so it is already a string, but the cast
        # means a future numeric key cannot break search at runtime.
        "id": str(display_id(advisory)),
        "pk": str(advisory.id),
        "title": advisory.title,
        "summary": advisory.summary,
        "description": advisory.description,
        "advisory_type": advisory.advisory_type,
        "severity": severity,
        "severity_variant": SEVERITY_VARIANTS.get(severity, "secondary"),
        "severity_rank": SEVERITY_RANK.get(severity, 0),
        # Two axes, deliberately. status_* is where the fix is, which is what the
        # list's Status column means and what the timeline drives. publication_*
        # is whether anyone outside the workspace can read it. The status_* names
        # match what the templates already bind to.
        "status": advisory.remediation_status,
        "status_label": remediation["label"],
        "status_variant": remediation["variant"],
        "status_icon": remediation["icon"],
        "status_rank": REMEDIATION_RANK.get(advisory.remediation_status, 0),
        "is_open": advisory.remediation_status not in SecurityAdvisory.CLOSED_REMEDIATION_STATUSES,
        "publication_status": advisory.status,
        "publication_label": advisory.get_status_display(),
        "publication_variant": PUBLICATION_VARIANTS.get(advisory.status, "secondary"),
        "visibility": advisory.visibility,
        "products": [_product_projection(p) for p in advisory.products.all()],
        "vulnerability_count": len(vulnerabilities),
        # The first CVE is what the list column shows; the detail page lists all.
        "vulnerability_id": next((v.cve_id for v in vulnerabilities if v.cve_id), ""),
        "type": advisory_type,
        "type_label": TYPE_LABELS[advisory_type],
        "updates_count": len(events),
        "created_at": advisory.created_at,
        "created_display": display_date(advisory.created_at),
        # "Updated" is the newest event of any kind, falling back to the row's
        # own timestamp for an advisory nobody has touched since creating it.
        "updated_at": updated_at,
        # Sortable and displayable forms of the same instant; the table sorts on
        # one and renders the other.
        "updated": updated_at.isoformat() if updated_at else "",
        "updated_display": display_date(updated_at),
        "published_at": advisory.published_at,
    }

    if detail:
        projection["vulnerabilities"] = [_vulnerability_projection(v) for v in vulnerabilities]
        projection["references"] = [_reference_projection(r) for r in references]
        # Newest first: the current state is the thing being looked for.
        newest_first = sorted(events, key=lambda e: e.created_at, reverse=True)
        projection["timeline"] = [_event_projection(e) for e in newest_first]
    return projection


def _base_queryset(team: Any) -> QuerySet[SecurityAdvisory]:
    """Advisories for one workspace, with the related rows the projection reads.

    Prefetched rather than left lazy: the list renders products, vulnerabilities
    and the newest event for every row, so without this each row costs three
    more queries.
    """
    return (
        SecurityAdvisory.objects.filter(team=team)
        .prefetch_related(
            Prefetch("vulnerabilities", queryset=AdvisoryVulnerability.objects.order_by("cve_id")),
            Prefetch("products", queryset=AdvisoryProduct.objects.select_related("product")),
            Prefetch("references", queryset=AdvisoryReference.objects.order_by("reference_type")),
            Prefetch("events", queryset=AdvisoryEvent.objects.select_related("actor").order_by("created_at")),
        )
        .order_by("-created_at")
    )


def list_advisories(team: Any, search: str = "") -> ServiceResult[list[dict[str, Any]]]:
    """The workspace's advisories, newest first."""
    queryset = _base_queryset(team)
    if search := (search or "").strip():
        queryset = (
            queryset.filter(title__icontains=search)
            | queryset.filter(tracking_id__icontains=search)
            | queryset.filter(vulnerabilities__cve_id__icontains=search)
        ).distinct()
    return ServiceResult.success([_advisory_projection(a) for a in queryset])


def get_advisory(team: Any, advisory_id: str) -> ServiceResult[dict[str, Any]]:
    """One advisory with its vulnerabilities, references and timeline.

    Looked up by tracking id as well as primary key, because the tracking id is
    what the list links and what a person pastes into the address bar. Scoped to
    the workspace, so another workspace's advisory reads as absent rather than
    forbidden.
    """
    # One queryset, one query: Q rather than a second lookup, so the prefetches
    # are not rebuilt and re-run for an advisory found by tracking id.
    advisory = _base_queryset(team).filter(Q(id=advisory_id) | Q(tracking_id=advisory_id)).first()
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)
    return ServiceResult.success(_advisory_projection(advisory, detail=True))


def advisory_counts(advisories: list[dict[str, Any]]) -> dict[str, int]:
    """Dashboard tallies, computed from the already-built list.

    Taken from the projection rather than as separate aggregate queries: the
    page has the rows in hand, and a second query could disagree with what is
    on screen.
    """
    return {
        "total": len(advisories),
        # "status" is the remediation axis and "publication_status" is the
        # draft/published one, matching what the templates bind to.
        "open": sum(1 for a in advisories if a["is_open"]),
        "resolved": sum(1 for a in advisories if a["status"] == "resolved"),
        "published": sum(1 for a in advisories if a["publication_status"] == "published"),
    }
