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
    AdvisoryReference,
    AdvisoryVersionRange,
    AdvisoryVulnerability,
    ReferenceType,
    SecurityAdvisory,
    Severity,
    validate_publishable,
)

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
    """A range the way a chip reads it: the bare version for a single-release
    pin, interval notation for a real span."""
    if version_range.introduced and version_range.introduced == version_range.last_affected:
        return version_range.introduced
    return str(version_range)


def _product_projection(advisory_product: AdvisoryProduct) -> dict[str, Any]:
    """A product chip.

    ``product`` is nullable and ``product_name`` carries the name when the FK is
    absent, so an advisory can name a product this workspace does not track and
    keep naming it after one is deleted. ``id`` is None in that case and the
    template renders plain text rather than a dead link.
    """
    product = advisory_product.product
    name = product.name if product else advisory_product.product_name
    # Deduplicated but order-preserving: two vulnerabilities citing the same
    # affected release should not print it twice on the chip.
    affected: dict[str, None] = {}
    for status in advisory_product.statuses.all():
        for version_range in status.version_ranges.all():
            affected.setdefault(_range_display(version_range))
    return {
        # A stable non-null key for x-for. ``id`` is null for an unlinked
        # product, and Alpine rejects that as a key, so two unlinked products
        # would also collide on it.
        "key": advisory_product.id,
        "id": product.id if product else None,
        "name": name,
        "affected_ranges": list(affected),
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
    best_cvss = worst_cvss(advisory)
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
            Prefetch(
                "products",
                queryset=AdvisoryProduct.objects.select_related("product").prefetch_related("statuses__version_ranges"),
            ),
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


def creation_options(team: Any) -> ServiceResult[list[dict[str, Any]]]:
    """Products and their pinnable releases, for the New Advisory pickers.

    ``latest`` releases are excluded: that pointer re-targets as artifacts
    arrive, so "affected: latest" would describe different code next month.

    Newest first, and the date travels with each row. Version strings do not
    sort into release order on their own — a hand-cut ``0.99-wiz-test`` can
    postdate a dated build — so without the date on screen a correctly ordered
    list reads as an unordered one.
    """
    releases_by_product: dict[str, list[dict[str, str]]] = {}
    release_rows = (
        Release.objects.filter(product__team=team, is_latest=False)
        .order_by("-created_at")
        .values("id", "product_id", "name", "version", "created_at")
    )
    for row in release_rows:
        label = row["version"] or row["name"]
        releases_by_product.setdefault(row["product_id"], []).append(
            {"id": row["id"], "label": label, "created": row["created_at"].strftime("%d %b %Y")}
        )

    products = [
        {"id": product_id, "name": name, "releases": releases_by_product.get(product_id, [])}
        for product_id, name in Product.objects.filter(team=team).order_by("name").values_list("id", "name")
    ]
    return ServiceResult.success(products)


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
        payload={"to": opening_status},
    )
    return ServiceResult.success(advisory.id)


# Above this, a value is described rather than quoted on the timeline. A
# rewritten description is the common case and pasting both versions of it
# would bury every other entry.
_FIELD_CHANGE_QUOTE_LIMIT = 80


# Fields whose display name is not just the field name recapitalised.
_FIELD_LABELS = {"cvss": "CVSS"}


def _field_change_body(field: str, old: Any, new: Any) -> str:
    """What a field_change entry reads as on the timeline."""
    label = _FIELD_LABELS.get(field, field.replace("_", " ").capitalize())

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
    cvss_score: str | None = None,
    cvss_vector: str | None = None,
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
    advisory = (
        SecurityAdvisory.objects.select_for_update()
        .filter(team=team)
        .filter(Q(id=advisory_id) | Q(tracking_id=advisory_id))
        .first()
    )
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
            payload={"field": "cvss", "old": old_display, "new": new_display},
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
            payload={"field": field, "old": old, "new": new},
        )
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
def publish_advisory(team: Any, user: Any, advisory_id: str, *, visibility: str) -> ServiceResult[str]:
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
    same maximum and one would lose to the unique constraint.
    """
    if visibility not in PUBLISHABLE_VISIBILITIES:
        return ServiceResult.failure("Choose whether to publish publicly or to NDA readers.", status_code=400)

    from sbomify.apps.teams.models import Team

    Team.objects.select_for_update().filter(pk=team.pk).first()

    advisory = (
        SecurityAdvisory.objects.select_for_update()
        .filter(team=team)
        .filter(Q(id=advisory_id) | Q(tracking_id=advisory_id))
        .first()
    )
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
        return ServiceResult.failure("; ".join(m for messages in error.message_dict.values() for m in messages), 400)

    advisory.save(update_fields=["status", "published_at", "visibility", "made_public_at", "tracking_id", "updated_at"])
    AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.PUBLISHED,
        actor=user,
        body=f"Published as {advisory.tracking_id} ({PUBLISHABLE_VISIBILITIES[visibility]['label'].lower()}).",
        payload={"visibility": visibility, "tracking_id": advisory.tracking_id},
    )
    return ServiceResult.success(advisory.id)


@transaction.atomic
def post_update(team: Any, user: Any, advisory_id: str, *, kind: str, note: str = "") -> ServiceResult[str]:
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
    advisory = (
        SecurityAdvisory.objects.select_for_update()
        .filter(team=team)
        .filter(Q(id=advisory_id) | Q(tracking_id=advisory_id))
        .first()
    )
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)

    kind = (kind or "").strip()
    note = note.strip()
    if kind == "update":
        if not note:
            return ServiceResult.failure("An update needs a note.", status_code=400)
        AdvisoryEvent.objects.create(
            advisory=advisory, event_type=AdvisoryEvent.EventType.UPDATE, actor=user, body=note
        )
        return ServiceResult.success(advisory.id)

    if kind not in SecurityAdvisory.RemediationStatus.values:
        return ServiceResult.failure("Unknown update type.", status_code=400)
    if kind == advisory.remediation_status:
        label = REMEDIATION_META.get(kind, {}).get("label", kind)
        return ServiceResult.failure(f"The advisory is already {label}.", status_code=400)

    AdvisoryEvent.objects.create(
        advisory=advisory,
        event_type=AdvisoryEvent.EventType.STATUS_CHANGE,
        actor=user,
        body=note,
        payload={"from": advisory.remediation_status, "to": kind},
    )
    advisory.remediation_status = kind
    advisory.save(update_fields=["remediation_status", "updated_at"])
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
    advisory.delete()
    return ServiceResult.success(advisory_id)


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
