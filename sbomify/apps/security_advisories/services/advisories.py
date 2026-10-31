"""Reading and creating advisories for the workspace UI.

The views render a projection rather than model instances, because the list and
detail pages want a few derived things the model deliberately does not store:
the display id, the worst severity across an advisory's vulnerabilities, and a
timeline that merges messages with status changes.

:func:`create_advisory` is the one write: the New Advisory modal's submission,
which builds the whole initial graph in a transaction.
"""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

from sbomify.apps.core.models import Product, Release
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.security_advisories.models import (
    CVE_ID_RE,
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryProposal,
    AdvisoryReference,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    ReferenceType,
    SecurityAdvisory,
    Severity,
    validate_publishable,
)
from sbomify.apps.teams.broadcasts import broadcast_on_commit

# Severity is not projected to a badge variant. c-badges.severity owns the five
# CVSS bands, and mapping them onto the generic semantic variants here shifted
# every band by one: high rendered in the amber the rest of the app uses for
# medium, medium in the blue it uses for low. Templates pass the raw band to
# c-badges.severity (or bind data-level for the Alpine twin) and the component
# picks the colour.
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

# How a per-product VEX assertion reads, on the workspace pages and the public
# ones alike. Same values as ``AdvisoryProductStatus.Status``; the labels are
# the model's own. Keyed by the plain string the column stores, not the enum, so
# a lookup on ``status.status`` (a ``str``) is the same type going in as coming
# out.
STATUS_VARIANTS: dict[str, str] = {
    AdvisoryProductStatus.Status.EXPLOITABLE: "danger",
    AdvisoryProductStatus.Status.IN_TRIAGE: "warning",
    AdvisoryProductStatus.Status.NOT_AFFECTED: "success",
    AdvisoryProductStatus.Status.FALSE_POSITIVE: "secondary",
    AdvisoryProductStatus.Status.RESOLVED: "success",
}

# Publication status to badge variant, the second axis on the list.
PUBLICATION_VARIANTS = {"draft": "secondary", "published": "success", "withdrawn": "warning"}

# Advisory "type" as the list column shows it. Inferred rather than stored,
# because the model already records the real identifiers and which database
# issued them is a fact about those, not a separate field to keep in step.
TYPE_LABELS = {"cve": "CVE", "ghsa": "GHSA", "internal": "Internal", "other": "Other"}

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
    "message_edited": {"label": "Edited", "variant": "secondary", "icon": "fas fa-pen"},
}
_UNKNOWN_EVENT = {"label": "Event", "variant": "secondary", "icon": "fas fa-circle"}


def display_id(advisory: SecurityAdvisory) -> str:
    """The id a human quotes.

    ``tracking_id`` is the workspace's own scheme (ACME-SA-2026-0034 and the like)
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
    # No external identifier anywhere means this is the workspace's own
    # finding, not some other database's. Saying "Internal" is more useful
    # than a catch-all that reads like the field failed to populate.
    if not types:
        return "internal"
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


# The version is written inside the vector ("CVSS:3.1/AV:N/…"), so a pasted
# vector names its own version and a bare score stores none rather than a
# guessed one.
_CVSS_VECTOR_VERSION_RE = re.compile(r"^CVSS:(\d+(?:\.\d+)?)/", re.IGNORECASE)


def cvss_entry(score: float, vector: str = "") -> dict[str, Any]:
    """One stored CVSS entry, in the shape ``AdvisoryVulnerability`` documents."""
    vector = vector.strip()
    match = _CVSS_VECTOR_VERSION_RE.match(vector)
    return {"version": match.group(1) if match else "", "vector": vector, "base_score": score}


def _best_cvss_entry(entries: Any) -> tuple[float, dict[str, Any]] | None:
    """The highest-scoring entry in one ``cvss_scores`` list, with its score.

    A hand-entered row can be absent or non-numeric; one bad row must not take
    the whole page down, so malformed entries are skipped rather than raised.
    """
    best: tuple[float, dict[str, Any]] | None = None
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        try:
            score = float(entry["base_score"])
        except (KeyError, TypeError, ValueError):
            continue
        if best is None or score > best[0]:
            best = (score, entry)
    return best


def worst_cvss(advisory: SecurityAdvisory) -> dict[str, Any] | None:
    """The highest-scoring CVSS entry across the advisory's vulnerabilities.

    The pages lead with one number, and an advisory carrying three CVEs must
    not read as the mildest of them. Returns None when nobody scored it.
    """
    best: tuple[float, dict[str, Any]] | None = None
    for vulnerability in advisory.vulnerabilities.all():
        candidate = _best_cvss_entry(vulnerability.cvss_scores)
        if candidate and (best is None or candidate[0] > best[0]):
            best = candidate
    return best[1] if best else None


def _cvss_display(entry: dict[str, Any] | None) -> str:
    """A CVSS entry as the timeline quotes it: the score, then the vector."""
    if not entry:
        return ""
    score = float(entry["base_score"])
    vector = str(entry.get("vector") or "")
    return f"{score} ({vector})" if vector else str(score)


def _vulnerability_projection(vulnerability: AdvisoryVulnerability) -> dict[str, Any]:
    return {
        "id": vulnerability.id,
        "cve_id": vulnerability.cve_id,
        "title": vulnerability.title,
        "description": vulnerability.description,
        "severity": vulnerability.severity,
        "cwe_ids": vulnerability.cwe_ids or [],
        "cvss_scores": vulnerability.cvss_scores or [],
        "exploitation_status": vulnerability.exploitation_status,
        "recommendation": vulnerability.recommendation,
    }


def _range_display(version_range: AdvisoryVersionRange) -> str:
    """A range as the API returns it: the bare version for a single-release pin,
    interval notation for a real span."""
    if version_range.introduced and version_range.introduced == version_range.last_affected:
        return version_range.introduced
    return str(version_range)


def version_range_label(version_range: AdvisoryVersionRange) -> str:
    """A range in words, for a page rather than an API: the bare version for a
    pin, and a phrase rather than interval notation for a real span."""
    introduced = version_range.introduced
    fixed = version_range.fixed
    last = version_range.last_affected
    if introduced and introduced == last:
        return introduced
    if introduced and fixed:
        return f"From {introduced}, fixed in {fixed}"
    if introduced and last:
        return f"{introduced} to {last}"
    if fixed:
        return f"Before {fixed}"
    if last:
        return f"{last} and earlier"
    if introduced:
        return f"{introduced} and later"
    return "All versions"


def _product_projection(advisory_product: AdvisoryProduct) -> dict[str, Any]:
    """One affected product and its affected versions, as the detail page lists them.

    ``product`` is nullable and ``product_name`` carries the name when the FK is
    absent, so an advisory can name a product this workspace does not track and
    keep naming it after one is deleted. ``id`` is None in that case and the
    template renders plain text rather than a dead link.
    """
    product = advisory_product.product
    name = product.name if product else advisory_product.product_name
    # Deduplicated but order-preserving: two vulnerabilities citing the same
    # affected release should not list it twice.
    affected: dict[str, None] = {}
    labels: dict[str, None] = {}
    for status in advisory_product.statuses.all():
        for version_range in status.version_ranges.all():
            affected.setdefault(_range_display(version_range))
            labels.setdefault(version_range_label(version_range))
    return {
        # A stable non-null key for x-for. ``id`` is null for an unlinked
        # product, and Alpine rejects that as a key, so two unlinked products
        # would also collide on it.
        "key": advisory_product.id,
        "id": product.id if product else None,
        "name": name,
        "affected_ranges": list(affected),
        "affected_versions": list(labels),
    }


def _status_projection(status: AdvisoryProductStatus, *, many_vulnerabilities: bool) -> dict[str, Any]:
    """One product status row, as the "Product statuses" table and its edit dialog read it."""
    advisory_product = status.advisory_product
    product = advisory_product.product if advisory_product else None
    subject = status_subject(status)
    vulnerability = _vulnerability_label(status.vulnerability)
    # From the prefetch: one range at most carries ``fixed``.
    fix = next((r for r in status.version_ranges.all() if r.fixed), None)
    return {
        "id": status.id,
        "label": f"{subject} ({vulnerability})" if many_vulnerabilities else subject,
        "product": subject,
        "product_id": product.id if product else None,
        "advisory_product_id": advisory_product.id if advisory_product else None,
        "is_component": status.advisory_component_id is not None,
        "vulnerability": vulnerability,
        "vulnerability_id": status.vulnerability_id,
        "status": status.status,
        "status_label": status.get_status_display(),
        "status_variant": STATUS_VARIANTS.get(status.status, "secondary"),
        "is_open": status.status in OPEN_PRODUCT_STATES,
        "justification": status.justification,
        "justification_label": status.get_justification_display() if status.justification else "",
        "response": status.response,
        "response_label": status.get_response_display() if status.response else "",
        "impact_statement": status.impact_statement,
        "action_statement": status.action_statement,
        "recommended_version": status.recommended_version,
        "recommended_release_id": status.recommended_release_id,
        "fixed_version": fix.fixed if fix else "",
        "fixed_release_id": fix.fixed_release_id if fix else None,
        # Every range but a bare fix: one that also says where the bug came
        # in is an affected span, which the Trust Center lists too.
        "affected_versions": [_range_display(r) for r in status.version_ranges.all() if not r.fixed or r.introduced],
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


def latest_edits(events: list[AdvisoryEvent]) -> dict[str, AdvisoryEvent]:
    """The newest ``message_edited`` event for each message that has one.

    ``events`` must be oldest first, as every prefetch here orders them, so a
    later edit overwrites an earlier one.
    """
    edits: dict[str, AdvisoryEvent] = {}
    for event in events:
        if event.event_type == AdvisoryEvent.EventType.MESSAGE_EDITED:
            payload = event.payload if isinstance(event.payload, dict) else {}
            if target := payload.get("event_id"):
                edits[str(target)] = event
    return edits


def _actor_name(user: Any) -> str:
    return (user.get_full_name() or user.username) if user else ""


def _event_projection(event: AdvisoryEvent, edit: AdvisoryEvent | None = None) -> dict[str, Any]:
    meta = EVENT_META.get(event.event_type, _UNKNOWN_EVENT)
    payload = event.payload if isinstance(event.payload, dict) else {}
    actor = event.actor
    via = payload["via"] if isinstance(payload.get("via"), dict) else {}

    # A status change reads as the state it moved to, not as the words
    # "Status change" — five entries all labelled the same tell a reader
    # nothing about what happened. The badge takes the state's own colour
    # and icon for the same reason.
    label, variant, icon = meta["label"], meta["variant"], meta["icon"]
    to_status = payload.get("to")
    if event.event_type == AdvisoryEvent.EventType.STATUS_CHANGE and to_status in REMEDIATION_META:
        state_meta = REMEDIATION_META[to_status]
        label, variant, icon = state_meta["label"], state_meta["variant"], state_meta["icon"]

    return {
        "id": event.id,
        "kind": event.event_type,
        "label": label,
        "variant": variant,
        "icon": icon,
        # The transition's origin, for a reader who wants the before as well
        # as the after. Absent on the first change, which came from nowhere.
        "from_label": REMEDIATION_META.get(payload.get("from", ""), {}).get("label", ""),
        # "note" and "date_display" are what the timeline template binds to;
        # "body" and "created_at" are the model's own names, kept for callers
        # that want the raw values. Both carry the newest edit, if any.
        "note": edit.body if edit else event.body,
        "date_display": display_date(event.created_at),
        "body": edit.body if edit else event.body,
        "is_editable": event.event_type in AdvisoryEvent.EDITABLE_EVENT_TYPES,
        "edited_at": edit.created_at if edit else None,
        "edited_display": display_date(edit.created_at) if edit else "",
        "edited_by": _actor_name(edit.actor) if edit else "",
        "payload": payload,
        # Only status_change moves the advisory's remediation status; the rest
        # are narrative. The template greys the others accordingly.
        "sets_status": event.event_type == AdvisoryEvent.EventType.STATUS_CHANGE,
        "to_status": payload.get("to"),
        "from_status": payload.get("from"),
        "actor": _actor_name(actor),
        # How the change was sent: "agent", "api" or "ci" through the API, blank
        # for the app and for anything recorded before this was kept.
        "channel": via.get("channel", ""),
        "token_id": via.get("token_id", ""),
        # Set when a person approved a change an AI agent proposed.
        "approved_by": via.get("approved_by", ""),
        "edit_channel": ((edit.payload or {}).get("via") or {}).get("channel", "") if edit else "",
        "edit_approved_by": ((edit.payload or {}).get("via") or {}).get("approved_by", "") if edit else "",
        "is_internal": event.event_type == AdvisoryEvent.EventType.COMMENT,
        "created_at": event.created_at,
    }


def _advisory_projection(advisory: SecurityAdvisory, *, detail: bool = False) -> dict[str, Any]:
    severity = worst_severity(advisory)
    best_cvss = worst_cvss(advisory)
    remediation = REMEDIATION_META.get(advisory.remediation_status, _UNKNOWN_EVENT)
    all_events = list(advisory.events.all())
    # An edit is shown in place of the message it edits, not as an entry of
    # its own, but it still counts as the advisory being updated.
    edits = latest_edits(all_events)
    events = [e for e in all_events if e.event_type != AdvisoryEvent.EventType.MESSAGE_EDITED]
    vulnerabilities = list(advisory.vulnerabilities.all())
    references = list(advisory.references.all())
    advisory_type = _advisory_type(vulnerabilities, references)
    updated_at = max((e.created_at for e in all_events), default=advisory.updated_at)

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
        "severity_rank": SEVERITY_RANK.get(severity, 0),
        # The same worst-entry the trust center leads with, plus its vector so
        # the edit form can prefill what the page displays.
        "cvss_score": float(best_cvss["base_score"]) if best_cvss else None,
        "cvss_vector": str(best_cvss.get("vector") or "") if best_cvss else "",
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
        "withdrawn_at": advisory.withdrawn_at,
        "withdrawal_reason": advisory.withdrawal_reason,
    }

    if detail:
        projection["vulnerabilities"] = [_vulnerability_projection(v) for v in vulnerabilities]
        many = len(vulnerabilities) > 1
        projection["statuses"] = [
            _status_projection(status, many_vulnerabilities=many)
            for vulnerability in vulnerabilities
            for status in vulnerability.product_statuses.all()
        ]
        projection["open_status_count"] = sum(1 for row in projection["statuses"] if row["is_open"])
        projection["references"] = [_reference_projection(r) for r in references]
        # Newest first: the current state is the thing being looked for.
        newest_first = sorted(events, key=lambda e: e.created_at, reverse=True)
        projection["timeline"] = [_event_projection(e, edits.get(e.id)) for e in newest_first]
        # The first event is the creation, so its channel says who drafted it.
        first_via = (events[0].payload or {}).get("via") if events else None
        projection["drafted_by_agent"] = isinstance(first_via, dict) and first_via.get("channel") == "agent"
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
            Prefetch(
                "products",
                queryset=AdvisoryProduct.objects.select_related("product").prefetch_related("statuses__version_ranges"),
            ),
            Prefetch("references", queryset=AdvisoryReference.objects.order_by("reference_type")),
            Prefetch("events", queryset=AdvisoryEvent.objects.select_related("actor").order_by("created_at")),
        )
        .order_by("-created_at")
    )


def _filtered_queryset(team: Any, search: str = "", status: str | None = None) -> QuerySet[SecurityAdvisory]:
    """The workspace's advisories, narrowed but not yet projected."""
    queryset = _base_queryset(team)
    if search := (search or "").strip():
        queryset = (
            queryset.filter(title__icontains=search)
            | queryset.filter(tracking_id__icontains=search)
            | queryset.filter(vulnerabilities__cve_id__icontains=search)
        ).distinct()
    if status:
        queryset = queryset.filter(status=status)
    return queryset


def list_advisories(team: Any, search: str = "") -> ServiceResult[list[dict[str, Any]]]:
    """The workspace's advisories, newest first."""
    return ServiceResult.success([_advisory_projection(a) for a in _filtered_queryset(team, search)])


def list_advisories_page(
    team: Any,
    search: str = "",
    *,
    status: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> ServiceResult[tuple[list[dict[str, Any]], int]]:
    """One page of the workspace's advisories, and the total that matched.

    ``list_advisories`` projects every row because the page it was written for
    renders every row. A caller that shows twenty-five of two thousand should
    not pay for the other 1975: the projection sorts events, computes the worst
    severity and CVSS, and builds a timeline, on top of a four-way prefetch.
    Filtering and slicing happen in the database, and only the page is projected.
    """
    queryset = _filtered_queryset(team, search, status)
    total = queryset.count()
    rows = [_advisory_projection(a) for a in queryset[offset : offset + limit]]
    return ServiceResult.success((rows, total))


def get_advisory(team: Any, advisory_id: str) -> ServiceResult[dict[str, Any]]:
    """One advisory with its vulnerabilities, references and timeline.

    Looked up by tracking id as well as primary key, because the tracking id is
    what the list links and what a person pastes into the address bar. Scoped to
    the workspace, so another workspace's advisory reads as absent rather than
    forbidden.
    """
    # One queryset, one query: Q rather than a second lookup, so the prefetches
    # are not rebuilt and re-run for an advisory found by tracking id. The
    # status rows are the detail page's alone, so the list does not pay for them.
    advisory = (
        _base_queryset(team)
        .prefetch_related(
            Prefetch(
                "vulnerabilities__product_statuses",
                queryset=AdvisoryProductStatus.objects.select_related(
                    "vulnerability", "advisory_product__product", "advisory_component__component"
                ).prefetch_related("version_ranges"),
            )
        )
        .filter(Q(id=advisory_id) | Q(tracking_id=advisory_id))
        .first()
    )
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)
    return ServiceResult.success(_advisory_projection(advisory, detail=True))


def creation_options(team: Any, product_ids: list[str] | None = None) -> ServiceResult[list[dict[str, Any]]]:
    """Products and their pinnable releases, for the New Advisory pickers.

    ``product_ids`` narrows both to those products, for a page that only
    needs the releases of the products it already shows.

    ``latest`` releases are excluded: that pointer re-targets as artifacts
    arrive, so "affected: latest" would describe different code next month.

    Newest first, and the date travels with each row. Version strings do not
    sort into release order on their own — a hand-cut ``0.99-wiz-test`` can
    postdate a dated build — so without the date on screen a correctly ordered
    list reads as an unordered one.
    """
    releases_by_product: dict[str, list[dict[str, str]]] = {}
    releases = Release.objects.filter(product__team=team, is_latest=False)
    products = Product.objects.filter(team=team)
    if product_ids is not None:
        releases = releases.filter(product_id__in=product_ids)
        products = products.filter(id__in=product_ids)
    release_rows = releases.order_by("-created_at").values("id", "product_id", "name", "version", "created_at")
    for row in release_rows:
        label = row["version"] or row["name"]
        releases_by_product.setdefault(row["product_id"], []).append(
            {"id": row["id"], "label": label, "created": row["created_at"].strftime("%d %b %Y")}
        )

    options = [
        {"id": product_id, "name": name, "releases": releases_by_product.get(product_id, [])}
        for product_id, name in products.order_by("name").values_list("id", "name")
    ]
    return ServiceResult.success(options)


def product_choices(team: Any) -> ServiceResult[list[dict[str, str]]]:
    """The workspace's products by name, without their releases: what a product picker lists."""
    rows = Product.objects.filter(team=team).order_by("name").values_list("id", "name")
    return ServiceResult.success([{"id": product_id, "name": name} for product_id, name in rows])


def _stamped(payload: dict[str, Any], via: dict[str, str] | None) -> dict[str, Any]:
    """An event payload carrying how the change was sent, when the caller said.

    ``actor`` names the person, but every API token belongs to a person, so the
    actor alone cannot tell an owner's own edit from one their AI agent made
    with their token. ``via`` is that answer: the channel and the token id.
    """
    return {**payload, "via": via} if via else payload


def _announce(team: Any, advisory_id: Any, action: str) -> None:
    """Tell the workspace an advisory changed, so open advisory tables repaint.

    Every member hears this, drafts included, so it names the advisory and the
    action and nothing from its content.
    """
    broadcast_on_commit(team.key, "advisory_updated", {"advisory_id": str(advisory_id), "action": action})


def _locked_advisory(team: Any, advisory_id: str) -> SecurityAdvisory | None:
    """The advisory by id or tracking id, locked for a read-modify-write."""
    return (
        SecurityAdvisory.objects.select_for_update()
        .filter(team=team)
        .filter(Q(id=advisory_id) | Q(tracking_id=advisory_id))
        .first()
    )


def _messages(error: DjangoValidationError) -> str:
    """A model's validation errors as one line a toast or an API detail can carry."""
    if hasattr(error, "error_dict"):
        return "; ".join(m for messages in error.message_dict.values() for m in messages)
    return "; ".join(error.messages)


@transaction.atomic
def create_advisory(
    team: Any,
    user: Any,
    *,
    title: str,
    severity: str = "",
    description: str = "",
    identifier: str = "",
    remediation_status: str = "",
    cvss_score: float | None = None,
    cvss_vector: str = "",
    products: list[Product] | None = None,
    affected_releases: list[Release] | None = None,
    via: dict[str, str] | None = None,
) -> ServiceResult[str]:
    """The New Advisory modal's write: the whole initial graph, atomically.

    One vulnerability row is always created. A CVE identifier becomes its
    ``cve_id``; any other identifier is stored as an :class:`AdvisoryReference`
    (a GHSA cannot live in ``cve_id``, which validates strictly) and the
    vulnerability keeps the advisory's title as its working name — the model's
    own vocabulary for a finding with no id yet. A CVSS score lands on that
    vulnerability as the single entry the form manages.

    Every product gets an ``in_triage`` status per the vulnerability from
    birth, which is the shape :func:`~..models.validate_publishable` will
    demand at publish time. Each affected release becomes a single-version
    range pinned to that release, so the advisory keeps naming the version
    after the release row is ever deleted.
    """
    # An advisory written up after the work began opens at the status it is
    # actually at, and its first timeline entry records that rather than a
    # fictional "identified" the team would have to correct.
    opening_status = remediation_status or SecurityAdvisory.RemediationStatus.IDENTIFIED.value
    # Every product opens under investigation, and a resolved advisory must not
    # say that about any of them.
    if opening_status == SecurityAdvisory.RemediationStatus.RESOLVED and products:
        return ServiceResult.failure(
            "An advisory with products cannot open as resolved. Create it, set each product's status, then resolve it.",
            status_code=400,
        )

    advisory = SecurityAdvisory.objects.create(
        team=team,
        title=title.strip(),
        severity=severity,
        description=description.strip(),
        remediation_status=opening_status,
        created_by=user,
    )

    # Normalised here as well as in the form, so a caller passing cve-2026-1
    # directly gets a CVE rather than a misfiled reference.
    identifier = identifier.strip()
    is_cve = bool(CVE_ID_RE.match(identifier.upper()))
    if is_cve:
        identifier = identifier.upper()
    vulnerability = AdvisoryVulnerability.objects.create(
        advisory=advisory,
        cve_id=identifier if is_cve else "",
        title="" if is_cve else advisory.title,
        cvss_scores=[cvss_entry(cvss_score, cvss_vector)] if cvss_score is not None else [],
    )
    if identifier and not is_cve:
        is_url = identifier.lower().startswith(("http://", "https://"))
        AdvisoryReference.objects.create(
            advisory=advisory,
            external_id="" if is_url else identifier,
            url=identifier if is_url else "",
        )

    status_by_product: dict[str, AdvisoryProductStatus] = {}
    for product in products or []:
        advisory_product = AdvisoryProduct.objects.create(advisory=advisory, product=product)
        status_by_product[product.id] = AdvisoryProductStatus.objects.create(
            vulnerability=vulnerability, advisory_product=advisory_product
        )
    # Cross-tenant products need no check here: AdvisoryProduct.clean rejects
    # them, and a foreign release falls out of status_by_product below. The
    # floating "latest" is the one thing only the form was refusing.
    for release in affected_releases or []:
        if release.is_latest:
            transaction.set_rollback(True)
            return ServiceResult.failure("The floating latest release cannot be pinned as affected.", status_code=400)
        status = status_by_product.get(release.product_id)
        if status is None:
            # A failure result raises nothing, so the atomic block would commit
            # the half-built advisory without this.
            transaction.set_rollback(True)
            return ServiceResult.failure("Affected releases must belong to a selected product.", status_code=400)
        version = release.version or release.name
        AdvisoryVersionRange.objects.create(
            product_status=status,
            introduced=version,
            last_affected=version,
            introduced_release=release,
            last_affected_release=release,
        )

    AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.STATUS_CHANGE,
        actor=user,
        payload=_stamped({"to": opening_status}, via),
    )
    _announce(team, advisory.id, "created")
    return ServiceResult.success(advisory.id)


# Above this, a value is described rather than quoted on the timeline. A
# rewritten description is the common case and pasting both versions of it
# would bury every other entry.
_FIELD_CHANGE_QUOTE_LIMIT = 80


# Fields whose display name is not just the field name recapitalised.
_FIELD_LABELS = {"cvss": "CVSS"}


def _field_change_body(field: str, old: Any, new: Any, *, label: str | None = None) -> str:
    """What a field_change entry reads as on the timeline."""
    label = label or _FIELD_LABELS.get(field, field.replace("_", " ").capitalize())

    def describe(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        return f"“{text}”" if len(text) <= _FIELD_CHANGE_QUOTE_LIMIT else None

    old_text, new_text = describe(old), describe(new)
    if old_text and new_text:
        return f"{label} changed from {old_text} to {new_text}."
    if new_text and not old_text:
        return f"{label} set to {new_text}."
    if old_text and not new_text and not str(new or "").strip():
        return f"{label} cleared."
    return f"{label} updated."


@transaction.atomic
def update_advisory(
    team: Any,
    user: Any,
    advisory_id: str,
    *,
    title: str,
    severity: str | None = None,
    description: str = "",
    summary: str | None = None,
    cvss_score: str | None = None,
    cvss_vector: str | None = None,
    via: dict[str, str] | None = None,
) -> ServiceResult[str]:
    """Edit an advisory's own fields.

    Field changes land on the timeline as field_change events, one per field,
    so the append-only history answers "who changed the severity and when"
    rather than only recording status moves.

    CVSS lives on the advisory's vulnerability rather than the advisory row.
    The form manages one primary entry: the highest-scoring one is what the
    pages display and what the edit form prefills, so that is the entry an
    edit replaces and a blank submission clears. ``cvss_score`` arrives as the
    posted string; None means the form did not carry the field at all.
    """
    advisory = _locked_advisory(team, advisory_id)
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)

    title = title.strip()
    if not title:
        return ServiceResult.failure("An advisory needs a title.", status_code=400)

    # ``None`` means the caller did not submit a severity, which is different
    # from submitting a blank one. A <select> always posts something, so an
    # advisory saved with no severity would otherwise pick up the first option
    # whenever anyone edited its title.
    fields: list[tuple[str, Any]] = [("title", title), ("description", description.strip())]
    # The trust center leads with the summary. None leaves it alone, the same
    # rule severity follows, so a form without the field cannot blank it.
    if summary is not None:
        fields.append(("summary", summary.strip()))
    if severity is not None:
        severity = severity.strip()
        if severity and severity not in Severity.values:
            return ServiceResult.failure("Unknown severity.", status_code=400)
        fields.append(("severity", severity))

    cvss_changed = False
    new_entries: list[dict[str, Any]] = []
    holder: AdvisoryVulnerability | None = None
    old_entry: dict[str, Any] | None = None
    if cvss_score is not None:
        score_text = cvss_score.strip()
        vector = (cvss_vector or "").strip()
        if vector and not score_text:
            return ServiceResult.failure("Enter the CVSS score for the vector.", status_code=400)
        if score_text:
            try:
                score = float(score_text)
            except ValueError:
                return ServiceResult.failure("CVSS score must be a number from 0 to 10.", status_code=400)
            if not 0 <= score <= 10:
                return ServiceResult.failure("CVSS score must be a number from 0 to 10.", status_code=400)
            new_entries = [cvss_entry(score, vector)]

        # The entry being edited is the one the pages display, so the write
        # goes to the vulnerability holding it; an advisory with no scored
        # vulnerability falls back to its first, and one with no vulnerability
        # at all grows one below, the same shape create_advisory builds.
        vulnerabilities = list(advisory.vulnerabilities.all())
        best: tuple[float, dict[str, Any]] | None = None
        for candidate in vulnerabilities:
            found = _best_cvss_entry(candidate.cvss_scores)
            if found and (best is None or found[0] > best[0]):
                best, holder = found, candidate
        old_entry = best[1] if best else None
        if holder is None and vulnerabilities:
            holder = vulnerabilities[0]

        old_key = (float(old_entry["base_score"]), str(old_entry.get("vector") or "")) if old_entry else None
        new_key = (new_entries[0]["base_score"], new_entries[0]["vector"]) if new_entries else None
        cvss_changed = new_key != old_key

    changes = [(field, getattr(advisory, field), new) for field, new in fields if getattr(advisory, field) != new]
    if not changes and not cvss_changed:
        return ServiceResult.success(advisory.id)

    if changes:
        for field, _old, new in changes:
            setattr(advisory, field, new)
        advisory.save(update_fields=[field for field, _o, _n in changes] + ["updated_at"])

    if cvss_changed:
        if holder is None:
            AdvisoryVulnerability.objects.create(advisory=advisory, title=advisory.title, cvss_scores=new_entries)
        else:
            holder.cvss_scores = new_entries
            holder.save(update_fields=["cvss_scores", "updated_at"])
        old_display = _cvss_display(old_entry)
        new_display = _cvss_display(new_entries[0]) if new_entries else ""
        AdvisoryEvent.objects.create(
            advisory=advisory,
            event_type=AdvisoryEvent.EventType.FIELD_CHANGE,
            actor=user,
            body=_field_change_body("cvss", old_display, new_display),
            payload=_stamped({"field": "cvss", "old": old_display, "new": new_display}, via),
        )

    for field, old, new in changes:
        AdvisoryEvent.objects.create(
            advisory=advisory,
            event_type=AdvisoryEvent.EventType.FIELD_CHANGE,
            actor=user,
            # The timeline renders an event's body, so a field change with only
            # a payload showed a "Field change" badge and no text at all. The
            # body says which field moved; long values are summarised rather
            # than pasted, since a rewritten description would otherwise bury
            # every other entry on the page.
            body=_field_change_body(field, old, new),
            payload=_stamped({"field": field, "old": old, "new": new}, via),
        )
    _announce(team, advisory.id, "updated")
    return ServiceResult.success(advisory.id)


# Row states that leave a product's question open. A resolved advisory may not
# hold one: the trust center would say "Under investigation" or "Affected" next
# to a fix the advisory says shipped.
OPEN_PRODUCT_STATES = frozenset({AdvisoryProductStatus.Status.IN_TRIAGE, AdvisoryProductStatus.Status.EXPLOITABLE})

# What a product status edit may write. Anything else is refused rather than
# ignored, so a misspelt field cannot report success and store nothing.
#
# ``fixed_*`` is the first version carrying the fix, stored as the row's fixed
# range: it is what the affected and unaffected versions, and CSAF's ``fixed``
# products, are computed from. ``recommended_*`` is what users are told to move
# to. Setting the fix without a recommendation recommends the fix.
PRODUCT_STATUS_FIELDS = frozenset(
    {
        "status",
        "justification",
        "response",
        "impact_statement",
        "action_statement",
        "recommended_version",
        "recommended_release_id",
        "fixed_version",
        "fixed_release_id",
    }
)

# How a product status field reads on the timeline.
_STATUS_FIELD_LABELS = {
    "status": "Status",
    "justification": "Justification",
    "response": "Response",
    "impact_statement": "Impact",
    "action_statement": "What users should do",
    "recommended_version": "Recommended version",
    "fixed_version": "Fixed in",
}


class _Refused(Exception):
    """A product status write the caller has to change, carrying its HTTP status."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def status_subject(status: AdvisoryProductStatus) -> str:
    """What a status row speaks about: its product, its component, or the whole portfolio.

    The product's live name when it is still tracked, the retained name when it
    is not. Shared with the trust center so the two pages cannot name a row
    differently.
    """
    if status.advisory_product is not None:
        product = status.advisory_product.product
        return product.name if product else status.advisory_product.product_name
    if status.advisory_component is not None:
        component = status.advisory_component.component
        return component.name if component else status.advisory_component.component_name
    return "All products"


def _vulnerability_label(vulnerability: AdvisoryVulnerability) -> str:
    return vulnerability.cve_id or vulnerability.title or vulnerability.id


def _fix_range(status: AdvisoryProductStatus) -> AdvisoryVersionRange | None:
    """The row's range carrying a ``fixed`` endpoint, read from the table.

    A range holds ``fixed`` or ``last_affected``, never both, so the fix gets a
    range of its own rather than being added to an affected-release pin. Not
    from a prefetch: the edit that reads it may have just replaced it.
    """
    if status._state.adding:
        return None
    return (
        AdvisoryVersionRange.objects.filter(product_status=status)
        .exclude(fixed="")
        .select_related("fixed_release")
        .order_by("created_at")
        .first()
    )


def _open_status_labels(advisory: SecurityAdvisory) -> list[str]:
    """The rows that would contradict a resolved advisory, named for a person."""
    rows = (
        AdvisoryProductStatus.objects.filter(vulnerability__advisory=advisory, status__in=OPEN_PRODUCT_STATES)
        .select_related(
            "vulnerability",
            "advisory_product__product",
            "advisory_component__component",
        )
        .order_by("created_at")
    )
    many = advisory.vulnerabilities.count() > 1
    labels = []
    for row in rows:
        subject = status_subject(row)
        if many:
            subject = f"{subject} ({_vulnerability_label(row.vulnerability)})"
        labels.append(f"{subject} is {row.get_status_display()}")
    return labels


def _status_snapshot(status: AdvisoryProductStatus) -> dict[str, str]:
    """The row as the timeline quotes it: labels, not stored tokens."""
    fix = _fix_range(status)
    return {
        "status": status.get_status_display(),
        "justification": status.get_justification_display() if status.justification else "",
        "response": status.get_response_display() if status.response else "",
        "impact_statement": status.impact_statement,
        "action_statement": status.action_statement,
        "recommended_version": status.recommended_version,
        "fixed_version": fix.fixed if fix else "",
    }


def _pinnable_release(team: Any, release_id: Any, *, role: str) -> Release | None:
    """A release from this workspace that may name a fix, or None to clear the pin."""
    if not release_id:
        return None
    release = Release.objects.filter(pk=release_id, product__team=team).first()
    if release is None:
        raise _Refused(f"The {role} release was not found.", 404)
    if release.is_latest:
        # It re-targets as artifacts arrive, so "fixed in latest" would name
        # different code next month.
        raise _Refused(f"The floating latest release cannot be the {role} release.")
    return release


def _apply_status_changes(
    team: Any, advisory: SecurityAdvisory, status: AdvisoryProductStatus, changes: dict[str, Any]
) -> None:
    """Write ``changes`` to one row and its fixed range. Raises ``_Refused``."""
    choices = AdvisoryProductStatus
    original = None if status._state.adding else {column: getattr(status, column) for column in _STATUS_COLUMNS}
    if "status" in changes:
        value = (changes["status"] or "").strip()
        if value not in choices.Status.values:
            raise _Refused(f"Unknown status. Use one of: {', '.join(choices.Status.values)}.")
        if (
            advisory.remediation_status == SecurityAdvisory.RemediationStatus.RESOLVED
            and value in OPEN_PRODUCT_STATES
            and value != status.status
        ):
            raise _Refused(
                f"This advisory is resolved, so {status_subject(status)} cannot be "
                f"{choices.Status(value).label}. Reopen it first.",
                409,
            )
        status.status = value
        # A justification only explains "not affected". Moving off it drops the
        # old one, or the row could not be saved at all.
        if value != choices.Status.NOT_AFFECTED and "justification" not in changes:
            status.justification = ""
    for field, enum in (("justification", choices.Justification), ("response", choices.Response)):
        if field in changes:
            value = (changes[field] or "").strip()
            if value and value not in enum.values:
                raise _Refused(f"Unknown {field}. Use one of: {', '.join(enum.values)}.")
            setattr(status, field, value)
    for field in ("impact_statement", "action_statement"):
        if field in changes:
            setattr(status, field, (changes[field] or "").strip())

    if "recommended_release_id" in changes:
        recommended = _pinnable_release(team, changes["recommended_release_id"], role="recommended")
        status.recommended_release = recommended
        status.recommended_version = _pinned_version(
            (changes.get("recommended_version") or "").strip(), recommended, role="recommended"
        )
    elif "recommended_version" in changes:
        version = (changes["recommended_version"] or "").strip()
        pinned = status.recommended_release
        # A typed version that is not the pinned release's drops the pin, so
        # the two can never name different versions.
        if not version or (pinned is not None and version not in (pinned.version, pinned.name)):
            status.recommended_release = None
        status.recommended_version = version

    if "fixed_version" in changes or "fixed_release_id" in changes:
        fix = _fix_range(status)
        old_fix_version = fix.fixed if fix else ""
        typed = (changes.get("fixed_version") or "").strip()
        if "fixed_release_id" in changes:
            fixed_release = _pinnable_release(team, changes["fixed_release_id"], role="fixed")
        else:
            fixed_release = fix.fixed_release if fix else None
            if fixed_release is not None and typed not in (fixed_release.version, fixed_release.name):
                fixed_release = None
        fixed_version = _pinned_version(typed, fixed_release, role="fixed")

        # The fix is what users move to, unless the caller said otherwise or
        # the row already recommended something other than the old fix.
        if (
            "recommended_version" not in changes
            and "recommended_release_id" not in changes
            and status.recommended_version in ("", old_fix_version)
        ):
            status.recommended_version = fixed_version
            status.recommended_release = fixed_release

        # The row first: a new one has to exist before a range can point at it.
        _save_status(status, original)
        if fix is None and not fixed_version:
            return
        if fix is None:
            fix = AdvisoryVersionRange(product_status=status)
        elif fix.fixed == fixed_version and fix.fixed_release_id == (fixed_release.pk if fixed_release else None):
            # Unchanged: a save would still move the public CSAF revision.
            return
        if not fixed_version and not fix.introduced:
            fix.delete()
            return
        # Clearing a fix from a range that also says where the bug came in
        # keeps that range, now open-ended: losing the fix must not lose
        # the version that introduced it.
        fix.fixed = fixed_version
        fix.fixed_release = fixed_release if fixed_version else None
        try:
            fix.save()
        except DjangoValidationError as error:
            raise _Refused(_messages(error)) from error
        return

    _save_status(status, original)


def _pinned_version(typed: str, release: Release | None, *, role: str) -> str:
    """The version a pin stands for: the release's own, or a typed one that agrees with it."""
    if release is None:
        return typed
    if typed and typed not in (release.version, release.name):
        raise _Refused(f"The {role} version {typed} is not the version of the release chosen with it.")
    return release.version or release.name


# The row's own columns an edit can move. A save that moves none is skipped,
# because a save alone advances the public CSAF revision.
_STATUS_COLUMNS = (
    "status",
    "justification",
    "response",
    "impact_statement",
    "action_statement",
    "recommended_version",
    "recommended_release_id",
)


def _save_status(status: AdvisoryProductStatus, original: dict[str, Any] | None) -> None:
    if original is not None and all(getattr(status, column) == original[column] for column in _STATUS_COLUMNS):
        return
    try:
        status.save()
    except DjangoValidationError as error:
        raise _Refused(_messages(error)) from error


def _record_status_changes(
    advisory: SecurityAdvisory,
    user: Any,
    status: AdvisoryProductStatus,
    before: dict[str, str],
    via: dict[str, str] | None,
    *,
    many_vulnerabilities: bool,
) -> bool:
    """One internal field_change per changed field. True when anything changed."""
    after = _status_snapshot(status)
    subject = status_subject(status)
    if many_vulnerabilities:
        subject = f"{subject} ({_vulnerability_label(status.vulnerability)})"
    changed = False
    for field, label in _STATUS_FIELD_LABELS.items():
        if before[field] == after[field]:
            continue
        changed = True
        body = _field_change_body(field, before[field], after[field], label=label)
        AdvisoryEvent.objects.create(
            advisory=advisory,
            event_type=AdvisoryEvent.EventType.FIELD_CHANGE,
            actor=user,
            body=f"{subject}: {body}",
            payload=_stamped(
                {
                    "field": f"product_status.{field}",
                    "old": before[field],
                    "new": after[field],
                    "status_id": status.id,
                    "subject": subject,
                },
                via,
            ),
        )
    return changed


def _publish_problems(advisory: SecurityAdvisory) -> set[str] | None:
    """What a published advisory already fails, before an edit. None for an unpublished one."""
    if advisory.status != SecurityAdvisory.Status.PUBLISHED:
        return None
    return set(validate_publishable(advisory))


def _refuse_new_publish_problems(advisory: SecurityAdvisory, before: set[str] | None) -> None:
    """A published advisory keeps the shape publishing demanded of it.

    Only problems this edit introduced are refused. One that was already there,
    on this row or another, must not block the edits that would repair the
    advisory a row at a time.
    """
    if before is None:
        return
    if introduced := [problem for problem in validate_publishable(advisory) if problem not in before]:
        raise _Refused(" ".join(introduced))


def _update_statuses(
    team: Any,
    user: Any,
    advisory: SecurityAdvisory,
    rows: list[AdvisoryProductStatus],
    changes: dict[str, Any],
    via: dict[str, str] | None,
) -> None:
    from sbomify.apps.security_advisories.signals import one_csaf_revision

    many = advisory.vulnerabilities.count() > 1
    problems = _publish_problems(advisory)
    changed = False
    with one_csaf_revision():
        for row in rows:
            before = _status_snapshot(row)
            _apply_status_changes(team, advisory, row, changes)
            changed = _record_status_changes(advisory, user, row, before, via, many_vulnerabilities=many) or changed
        if changed:
            _refuse_new_publish_problems(advisory, problems)
    if changed:
        _announce(team, advisory.id, "updated")


def _status_rows() -> QuerySet[AdvisoryProductStatus]:
    return AdvisoryProductStatus.objects.select_related(
        "vulnerability",
        "advisory_product__product",
        "advisory_component__component",
        "recommended_release",
    )


def _checked_changes(advisory: SecurityAdvisory | None, changes: dict[str, Any]) -> None:
    if advisory is None:
        raise _Refused("Advisory not found", 404)
    if advisory.status == SecurityAdvisory.Status.WITHDRAWN:
        raise _Refused("This advisory has been withdrawn, so its product statuses are final.", 409)
    if unknown := sorted(set(changes) - PRODUCT_STATUS_FIELDS):
        raise _Refused(f"Unknown field: {', '.join(unknown)}.")


@transaction.atomic
def update_product_status(
    team: Any,
    user: Any,
    advisory_id: str,
    status_id: str,
    *,
    changes: dict[str, Any],
    via: dict[str, str] | None = None,
) -> ServiceResult[str]:
    """Edit what one vulnerability means for one product: a partial update of one row.

    Only the fields in ``changes`` are written; see :data:`PRODUCT_STATUS_FIELDS`.
    The rows are the record, and the advisory is checked against them: a
    resolved advisory refuses a row moving back to open, a published one
    refuses an edit that would fail the rules it was published under, and a
    withdrawn one is final. Each changed field lands on the timeline as an
    internal field_change.
    """
    advisory = _locked_advisory(team, advisory_id)
    try:
        _checked_changes(advisory, changes)
        assert advisory is not None
        row = _status_rows().filter(pk=status_id, vulnerability__advisory=advisory).first()
        if row is None:
            raise _Refused("Product status not found", 404)
        _update_statuses(team, user, advisory, [row], changes, via)
    except _Refused as refused:
        transaction.set_rollback(True)
        return ServiceResult.failure(refused.message, status_code=refused.status_code)
    return ServiceResult.success(advisory.id)


@transaction.atomic
def update_product_statuses(
    team: Any,
    user: Any,
    advisory_id: str,
    product_id: str,
    *,
    changes: dict[str, Any],
    vulnerability_id: str | None = None,
    via: dict[str, str] | None = None,
) -> ServiceResult[str]:
    """The same edit, for every row of one product on the advisory.

    ``product_id`` is the sbomify product, or the advisory's own product row
    for a product the workspace does not track. An advisory usually carries
    one vulnerability, so this is the call that says "the Action is fixed in
    v2" without first looking up a row id; ``vulnerability_id`` narrows it to
    one vulnerability's row.
    """
    advisory = _locked_advisory(team, advisory_id)
    try:
        _checked_changes(advisory, changes)
        assert advisory is not None
        link = advisory.products.filter(Q(product_id=product_id) | Q(id=product_id)).first()
        if link is None:
            raise _Refused("This advisory does not name that product.", 404)
        rows = _status_rows().filter(advisory_product=link)
        if vulnerability_id:
            rows = rows.filter(vulnerability_id=vulnerability_id)
        found = list(rows.order_by("created_at"))
        if not found:
            raise _Refused("That product has no status on this advisory.", 404)
        _update_statuses(team, user, advisory, found, changes, via)
    except _Refused as refused:
        transaction.set_rollback(True)
        return ServiceResult.failure(refused.message, status_code=refused.status_code)
    return ServiceResult.success(advisory.id)


@transaction.atomic
def add_advisory_product(
    team: Any,
    user: Any,
    advisory_id: str,
    *,
    product: Product,
    affected_releases: list[Release] | None = None,
    changes: dict[str, Any] | None = None,
    via: dict[str, str] | None = None,
) -> ServiceResult[str]:
    """Name another product on an existing advisory, or more of its affected releases.

    A product missed at creation used to mean a new advisory. A new product
    gets a row per vulnerability, under investigation unless ``changes`` says
    otherwise, which a resolved advisory requires. Each release becomes a
    single-version range, as at creation. Naming a product already on the
    advisory adds only the releases it does not list yet: its status is its
    rows' to change, so ``changes`` for it are refused rather than dropped,
    and so is a call that would add nothing.
    """
    advisory = _locked_advisory(team, advisory_id)
    changes = changes or {}
    try:
        _checked_changes(advisory, changes)
        assert advisory is not None
        if advisory.advisory_type == SecurityAdvisory.AdvisoryType.WORKSPACE_NOTICE:
            raise _Refused("A workspace notice names no products.")
        if product.team_id != advisory.team_id:
            raise _Refused("Product not found", 404)
        for release in affected_releases or []:
            if release.is_latest:
                raise _Refused("The floating latest release cannot be pinned as affected.")
            if release.product_id != product.id:
                raise _Refused("Affected releases must belong to the product being added.")

        from sbomify.apps.security_advisories.signals import one_csaf_revision

        problems = _publish_problems(advisory)
        link = advisory.products.filter(product=product).first()
        added = link is None
        if not added and changes:
            raise _Refused(f"{product.name} is already on this advisory. Change its status from its row instead.")

        with one_csaf_revision():
            if link is None:
                link = AdvisoryProduct.objects.create(advisory=advisory, product=product)
            rows = []
            for vulnerability in advisory.vulnerabilities.all():
                row = AdvisoryProductStatus.objects.filter(vulnerability=vulnerability, advisory_product=link).first()
                if row is None:
                    row = AdvisoryProductStatus(vulnerability=vulnerability, advisory_product=link)
                    _apply_status_changes(team, advisory, row, changes)
                    if (
                        advisory.remediation_status == SecurityAdvisory.RemediationStatus.RESOLVED
                        and row.status in OPEN_PRODUCT_STATES
                    ):
                        raise _Refused(
                            f"This advisory is resolved. Give {product.name} a status that is not "
                            f"{row.get_status_display()}, or reopen the advisory first.",
                            409,
                        )
                rows.append(row)

            new_versions: list[str] = []
            for release in affected_releases or []:
                version = release.version or release.name
                for row in rows:
                    if row.version_ranges.filter(last_affected_release=release).exists():
                        continue
                    AdvisoryVersionRange.objects.create(
                        product_status=row,
                        introduced=version,
                        last_affected=version,
                        introduced_release=release,
                        last_affected_release=release,
                    )
                    if version not in new_versions:
                        new_versions.append(version)

            if added:
                AdvisoryEvent.objects.create(
                    advisory=advisory,
                    event_type=AdvisoryEvent.EventType.PRODUCT_ADDED,
                    actor=user,
                    body=f"{product.name} added"
                    + (f", affected in {', '.join(new_versions)}." if new_versions else "."),
                    payload=_stamped({"product_id": product.id, "affected": new_versions}, via),
                )
            elif new_versions:
                AdvisoryEvent.objects.create(
                    advisory=advisory,
                    event_type=AdvisoryEvent.EventType.FIELD_CHANGE,
                    actor=user,
                    body=f"{product.name}: affected in {', '.join(new_versions)} as well.",
                    payload=_stamped(
                        {"field": "product.affected_releases", "old": "", "new": ", ".join(new_versions)}, via
                    ),
                )
            if not added and not new_versions:
                raise _Refused(f"{product.name} is already on this advisory with those releases.", 409)
            _refuse_new_publish_problems(advisory, problems)
    except _Refused as refused:
        transaction.set_rollback(True)
        return ServiceResult.failure(refused.message, status_code=refused.status_code)
    _announce(team, advisory.id, "updated")
    return ServiceResult.success(advisory.id)


# Publishing to "private" is not publishing: the Trust Center excludes private
# advisories in SQL, so it would move the status and disclose nothing. The two
# real destinations are a gated (embargoed, signed-NDA) disclosure and a public
# one; changing visibility afterwards is its own action.
PUBLISHABLE_VISIBILITIES: dict[str, dict[str, str]] = {
    SecurityAdvisory.Visibility.PUBLIC.value: {
        "label": "Public",
        "help": "Anyone can read it on your Trust Center.",
    },
    SecurityAdvisory.Visibility.GATED.value: {
        "label": "Gated",
        "help": "Only readers who have signed your NDA and can see an affected product.",
    },
}


@transaction.atomic
def publish_advisory(
    team: Any, user: Any, advisory_id: str, *, visibility: str, via: dict[str, str] | None = None
) -> ServiceResult[str]:
    """Disclose an advisory: the one write that makes it readable outside the workspace.

    Until this runs an advisory is a draft with private visibility, and the
    Trust Center filters both out — which is why a workspace could write
    advisories all day and see nothing published.

    Both axes move together here. Status alone would leave it private and still
    invisible; visibility alone would expose a draft. The tracking id is
    allocated now and is immutable afterwards, ``published_at`` records the
    disclosure, and ``made_public_at`` records it separately for a public one
    because a gated disclosure is not public disclosure.

    The team row is locked because ``allocate_tracking_id`` counts by reading
    the highest existing id for the year: two publishes racing would read the
    same maximum and one would lose to the unique constraint. The locked row
    also carries the current prefix and starting number.
    """
    if visibility not in PUBLISHABLE_VISIBILITIES:
        return ServiceResult.failure("Choose whether to publish publicly or to NDA readers.", status_code=400)

    from sbomify.apps.teams.models import Workspace

    # Allocate from the row just locked, not the caller's copy: numbering
    # settings saved since that copy was loaded must govern the new id.
    team = Workspace.objects.select_for_update().filter(pk=team.pk).first() or team

    advisory = _locked_advisory(team, advisory_id)
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)
    if advisory.status != SecurityAdvisory.Status.DRAFT:
        return ServiceResult.failure("This advisory has already been published.", status_code=409)

    # The graph-wide rules: a product advisory needs products, every
    # vulnerability needs a status per product, a fixed status names the fix.
    if problems := validate_publishable(advisory):
        return ServiceResult.failure(" ".join(problems), status_code=400)

    now = timezone.now()
    advisory.status = SecurityAdvisory.Status.PUBLISHED
    advisory.published_at = now
    advisory.visibility = visibility
    if visibility == SecurityAdvisory.Visibility.PUBLIC:
        advisory.made_public_at = now
    advisory.tracking_id = SecurityAdvisory.allocate_tracking_id(team)

    try:
        advisory.full_clean()
    except DjangoValidationError as error:
        # The model holds the disclosure invariants; surfacing them beats
        # letting a 500 out of save().
        return ServiceResult.failure(_messages(error), 400)

    advisory.save(update_fields=["status", "published_at", "visibility", "made_public_at", "tracking_id", "updated_at"])
    AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.PUBLISHED,
        actor=user,
        body=f"Published as {advisory.tracking_id} ({PUBLISHABLE_VISIBILITIES[visibility]['label'].lower()}).",
        payload=_stamped({"visibility": visibility, "tracking_id": advisory.tracking_id}, via),
    )
    _announce(team, advisory.id, "published")
    return ServiceResult.success(advisory.id)


@transaction.atomic
def withdraw_advisory(
    team: Any, user: Any, advisory_id: str, *, reason: str, via: dict[str, str] | None = None
) -> ServiceResult[str]:
    """Retract a published advisory without erasing that it was published.

    The row keeps its tracking id, its publication date and its visibility: a
    reader who cited the advisory can still resolve it, and the trust center
    goes on listing it, marked withdrawn and carrying the reason. Only a
    published advisory can be withdrawn: a draft has disclosed nothing, so the
    answer for one is a conflict that points the caller at delete.
    """
    reason = (reason or "").strip()
    if not reason:
        return ServiceResult.failure("Withdrawing an advisory requires a reason.", status_code=400)

    advisory = _locked_advisory(team, advisory_id)
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)
    if advisory.status == SecurityAdvisory.Status.WITHDRAWN:
        return ServiceResult.failure("This advisory has already been withdrawn.", status_code=409)
    if advisory.status != SecurityAdvisory.Status.PUBLISHED:
        return ServiceResult.failure(
            "Only a published advisory can be withdrawn; delete drafts instead.", status_code=409
        )

    advisory.status = SecurityAdvisory.Status.WITHDRAWN
    advisory.withdrawn_at = timezone.now()
    advisory.withdrawal_reason = reason
    try:
        advisory.full_clean()
    except DjangoValidationError as error:
        return ServiceResult.failure(_messages(error), 400)

    advisory.save(update_fields=["status", "withdrawn_at", "withdrawal_reason", "updated_at"])
    # A withdrawn advisory is final, so nothing still waiting for review can apply.
    advisory.proposals.filter(status=AdvisoryProposal.Status.PENDING).update(
        status=AdvisoryProposal.Status.SUPERSEDED, decided_at=timezone.now()
    )
    AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.WITHDRAWN,
        actor=user,
        body=reason,
        payload=_stamped({"reason": reason}, via),
    )
    _announce(team, advisory.id, "withdrawn")
    return ServiceResult.success(advisory.id)


@transaction.atomic
def post_update(
    team: Any, user: Any, advisory_id: str, *, kind: str, note: str = "", via: dict[str, str] | None = None
) -> ServiceResult[str]:
    """The timeline composer's write: a note, or a status move with commentary.

    ``kind`` is either ``update`` (a note that moves nothing) or a
    remediation status. Status kinds append the ``status_change`` event and
    keep the advisory's denormalised ``remediation_status`` in step with it,
    which is the invariant that field's help text promises.
    """
    # Locked for the read-modify-write below: payload["from"] and the
    # denormalised status both come from the row as read, so two concurrent
    # posts without the lock could record the same "from" and lose a
    # transition.
    advisory = _locked_advisory(team, advisory_id)
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)

    kind = (kind or "").strip()
    note = note.strip()
    if kind == "update":
        if not note:
            return ServiceResult.failure("An update needs a note.", status_code=400)
        AdvisoryEvent.objects.create(
            advisory=advisory,
            event_type=AdvisoryEvent.EventType.UPDATE,
            actor=user,
            body=note,
            payload=_stamped({}, via),
        )
        _announce(team, advisory.id, "updated")
        return ServiceResult.success(advisory.id)

    if kind not in SecurityAdvisory.RemediationStatus.values:
        return ServiceResult.failure("Unknown update type.", status_code=400)
    if kind == advisory.remediation_status:
        label = REMEDIATION_META.get(kind, {}).get("label", kind)
        return ServiceResult.failure(f"The advisory is already {label}.", status_code=400)
    if kind == SecurityAdvisory.RemediationStatus.RESOLVED and (open_rows := _open_status_labels(advisory)):
        # The rows are the record and the advisory is checked against them,
        # never the other way round: one advisory can be fixed in a different
        # version for each product, so nothing here can write the fix for them.
        return ServiceResult.failure(
            "Set a status for each product before resolving. Still open: " + "; ".join(open_rows) + ".",
            status_code=400,
        )

    AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.STATUS_CHANGE,
        actor=user,
        body=note,
        payload=_stamped({"from": advisory.remediation_status, "to": kind}, via),
    )
    advisory.remediation_status = kind
    advisory.save(update_fields=["remediation_status", "updated_at"])
    _announce(team, advisory.id, "updated")
    return ServiceResult.success(advisory.id)


def current_message(advisory: SecurityAdvisory, event_id: str) -> tuple[AdvisoryEvent | None, str]:
    """A timeline message that may be edited, and the text it reads as now."""
    event = advisory.events.filter(pk=event_id, event_type__in=AdvisoryEvent.EDITABLE_EVENT_TYPES).first()
    if event is None:
        return None, ""
    edit = (
        advisory.events.filter(event_type=AdvisoryEvent.EventType.MESSAGE_EDITED, payload__event_id=event.id)
        .order_by("-created_at")
        .first()
    )
    return event, edit.body if edit else event.body


@transaction.atomic
def edit_message(
    team: Any, user: Any, advisory_id: str, event_id: str, *, note: str, via: dict[str, str] | None = None
) -> ServiceResult[str]:
    """Correct the words of an update already on the timeline.

    The timeline is append-only, so the correction is a ``message_edited``
    event naming the message and keeping the text it replaced. Every reader,
    the Trust Center included, shows the newest text in the original's place,
    and the history of what it said stays on record.
    """
    advisory = _locked_advisory(team, advisory_id)
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)
    event, current = current_message(advisory, event_id)
    if event is None:
        return ServiceResult.failure("Update not found", status_code=404)
    note = (note or "").strip()
    if not note:
        return ServiceResult.failure("An update needs a note.", status_code=400)
    if note == current:
        return ServiceResult.success(advisory.id)

    AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.MESSAGE_EDITED,
        actor=user,
        body=note,
        payload=_stamped({"event_id": event.id, "event_type": event.event_type, "old": current}, via),
    )
    _announce(team, advisory.id, "updated")
    return ServiceResult.success(advisory.id)


def delete_advisory(team: Any, advisory_id: str) -> ServiceResult[str]:
    """Delete an advisory and everything hanging off it.

    The vulnerability rows, product statuses and timeline all cascade with the
    advisory, and nothing is recorded afterwards: the timeline that would carry
    the entry dies here. A published advisory disappears from the trust center,
    tracking id included, which is why the confirm dialog says so before this
    runs. Scoped to the workspace like every other lookup, so another
    workspace's advisory reads as absent rather than forbidden.
    """
    advisory = SecurityAdvisory.objects.filter(team=team).filter(Q(id=advisory_id) | Q(tracking_id=advisory_id)).first()
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)
    deleted_id = advisory.id
    advisory.delete()
    _announce(team, deleted_id, "deleted")
    return ServiceResult.success(advisory_id)


# The most advisories one bulk delete may name. Far past any page of the table,
# so the cap only ever stops a crafted request, not a person.
BULK_DELETE_LIMIT = 500


@transaction.atomic
def delete_advisories(team: Any, advisory_ids: list[str]) -> ServiceResult[int]:
    """Delete several advisories at once, as the table's bulk delete asks.

    Each id is matched the way delete_advisory matches one, by id or tracking
    id, and scoped to the workspace, so an id from another workspace matches
    nothing rather than being refused by name. Ids that match nothing are
    skipped: a row another person deleted a moment ago is not a reason to keep
    the rest. Only when none match is it a 404. All or nothing otherwise, in one
    transaction, so a failure part way leaves every advisory standing.
    """
    ids = list(dict.fromkeys(advisory_id.strip() for advisory_id in advisory_ids if advisory_id.strip()))
    if not ids:
        return ServiceResult.failure("Select at least one advisory", status_code=400)
    if len(ids) > BULK_DELETE_LIMIT:
        return ServiceResult.failure(f"Delete at most {BULK_DELETE_LIMIT} advisories at once", status_code=400)
    advisories = list(SecurityAdvisory.objects.filter(team=team).filter(Q(id__in=ids) | Q(tracking_id__in=ids)))
    if not advisories:
        return ServiceResult.failure("Advisories not found", status_code=404)
    for advisory in advisories:
        deleted_id = advisory.id
        advisory.delete()
        _announce(team, deleted_id, "deleted")
    return ServiceResult.success(len(advisories))


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
