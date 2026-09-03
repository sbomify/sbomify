"""Advisories as a trust-center visitor sees them.

The workspace view in ``advisories.py`` answers "what do we know about this
advisory". This module answers a different question — "what may *this* reader be
told" — and the two must not share a projection, because the workspace one
carries internal comments, draft rows and product names the reader may have no
business seeing.

Three rules decide what a visitor gets:

* ``PRIVATE`` never leaves the workspace, whatever its publication status.
* ``PUBLIC`` is readable by anyone once it is out of draft, including anonymous
  visitors.
* ``GATED`` needs two things at once: the workspace-level gated grant that
  ``core.services.access_control`` already enforces for components (an
  authenticated user who is a member or holds an approved access request, with
  the company NDA signed), **and** a link to at least one product the reader can
  actually reach in the trust center. A customer under NDA for the gateway
  should not read an embargoed advisory about a product they have never been
  shown.

The second half is what makes this per-advisory rather than per-workspace. It is
resolved once per request into a :class:`ViewerScope` — the set of product ids
the reader can reach — so filtering a page of advisories costs no extra queries
per row.

A workspace notice names no products by construction, so a gated one falls back
to the workspace-level grant alone; there is nothing narrower to test it against.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime
from datetime import timezone as dt_timezone
from math import ceil
from typing import Any

from django.db.models import Prefetch, Q
from django.utils.timesince import timesince

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.security_advisories.models import (
    AdvisoryEvent,
    AdvisoryProduct,
    AdvisoryProductStatus,
    AdvisoryReference,
    AdvisoryVulnerability,
    SecurityAdvisory,
)
from sbomify.apps.security_advisories.services.advisories import (
    PUBLICATION_VARIANTS,
    REMEDIATION_META,
    SEVERITY_RANK,
    display_date,
    display_id,
    worst_cvss,
    worst_severity,
)

# Statuses a reader may see at all. Draft is excluded by
# ``SecurityAdvisory.is_externally_visible``; withdrawn stays visible on purpose,
# because retracting a disclosure the public already read means saying so, not
# deleting it.
_READABLE_STATUSES = (SecurityAdvisory.Status.PUBLISHED, SecurityAdvisory.Status.WITHDRAWN)

# Severity facet order: worst first, which is the order a reader triages in.
# "none" is last and covers advisories nobody rated, so every row lands in
# exactly one bucket and the counts add up to the list length.
SEVERITY_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low", "none")

# Facet labels. Sentence case, not the stored token shouted back: a sidebar of
# CRITICAL / HIGH / MEDIUM reads as alarm rather than as a filter. "none" is
# labelled "Unrated" because "None" beside a checkbox reads as "match nothing"
# rather than "nobody scored this one".
SEVERITY_LABELS: dict[str, str] = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "none": "Unrated",
}

SORT_NEWEST = "newest"
SORT_OLDEST = "oldest"
SORT_SEVERITY = "severity"
SORT_OPTIONS: dict[str, str] = {
    SORT_NEWEST: "Newest",
    SORT_OLDEST: "Oldest",
    SORT_SEVERITY: "Severity",
}

DEFAULT_PER_PAGE = 25

# Timeline icons for the event kinds a visitor may read. A status_change borrows
# the icon of the state it moved to (see ``_public_event``); these cover the rest,
# so no entry falls back to a generic dot and the rail is readable without its
# labels.
EVENT_META: dict[str, dict[str, str]] = {
    AdvisoryEvent.EventType.PUBLISHED: {
        "label": "Published",
        "variant": "success",
        "icon": "fas fa-bullhorn",
    },
    AdvisoryEvent.EventType.UPDATE: {
        "label": "Update",
        "variant": "info",
        "icon": "fas fa-comment-dots",
    },
    AdvisoryEvent.EventType.WITHDRAWN: {
        "label": "Withdrawn",
        "variant": "warning",
        "icon": "fas fa-rotate-left",
    },
    AdvisoryEvent.EventType.STATUS_CHANGE: {
        "label": "Status change",
        "variant": "secondary",
        "icon": "fas fa-arrow-right-arrow-left",
    },
}
_DEFAULT_EVENT_META = {"label": "Event", "variant": "secondary", "icon": "fas fa-circle-info"}

# Sort fallback for an advisory with no publication date. Timezone-aware because
# ``published_at`` is, and comparing the two would otherwise raise.
_EPOCH = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)

# How a per-product VEX assertion reads on a public page. Same values as
# ``AdvisoryProductStatus.Status``; the labels are the model's own. Keyed by the
# plain string the column stores, not the enum, so a lookup on ``status.status``
# (a ``str``) is the same type going in as coming out.
STATUS_VARIANTS: dict[str, str] = {
    AdvisoryProductStatus.Status.EXPLOITABLE: "danger",
    AdvisoryProductStatus.Status.IN_TRIAGE: "warning",
    AdvisoryProductStatus.Status.NOT_AFFECTED: "success",
    AdvisoryProductStatus.Status.FALSE_POSITIVE: "secondary",
    AdvisoryProductStatus.Status.RESOLVED: "success",
}


@dataclass(frozen=True)
class ViewerScope:
    """What one reader may be shown, resolved once per request.

    ``product_ids`` is the whole point: the products this reader can reach in the
    trust center. It does two jobs — deciding whether a gated advisory is theirs
    to read, and deciding which product names an advisory may print — and both
    have to agree, or an advisory would name a product whose page 404s.

    ``has_gated_grant`` is the workspace-level half (authenticated, member or
    approved access request, NDA signed). It is necessary for a gated advisory
    but not sufficient.
    """

    has_gated_grant: bool
    product_ids: frozenset[str]
    is_authenticated: bool
    is_insider: bool

    def may_read(self, visibility: str, advisory_product_ids: frozenset[str]) -> bool:
        if visibility == SecurityAdvisory.Visibility.PUBLIC:
            return True
        if visibility != SecurityAdvisory.Visibility.GATED:
            return False
        if not self.has_gated_grant:
            return False
        # A notice names no products, so the workspace grant is the whole test:
        # there is nothing narrower to check it against.
        if not advisory_product_ids:
            return True
        return bool(advisory_product_ids & self.product_ids)


def resolve_viewer_scope(request: Any, team: Any) -> ViewerScope:
    """The reader's reach into one workspace, in two queries at most.

    Three tiers, widening:

    * **Anonymous or unapproved** — the products the trust center already lists
      to the world (public, with at least one public component). Their names are
      not secret, so a public advisory may print them.
    * **Gated grant** — adds products whose components are gated. This is the
      NDA-holding customer, and it is the tier the visibility rule was written
      for.
    * **Workspace insider** — anyone holding ``product:read``, i.e. every
      internal role (owner, admin, member): every product, including ones the
      trust center never lists, so an advisory about an unlisted product is
      readable internally and nobody else.

      Derived from the capability rather than a hand-picked tier. This is a read
      gate over product data, so it has to follow ``product:read`` or the same
      person sees different inventory depending on which page they open. It
      discloses nothing new: the internal advisory views
      (``core/views/security_advisories.py``) carry no role tier at all, so an
      internal member can already read every advisory there — including drafts
      and PRIVATE ones, which this page never shows anyone.

    The gated decision itself is delegated to ``_check_gated_access`` rather than
    re-derived, so an advisory and a component cannot disagree about who is
    inside the NDA.
    """
    from sbomify.apps.core.authz import can
    from sbomify.apps.core.models import Product
    from sbomify.apps.core.services.access_control import _check_gated_access
    from sbomify.apps.sboms.models import Component

    user = getattr(request, "user", None)
    is_authenticated = user is not None and bool(user.is_authenticated)

    has_gated_grant = False
    is_insider = False
    if user is not None and is_authenticated:
        has_gated_grant, _needs_nda = _check_gated_access(user, team)
        is_insider = can(user, "product:read", team).allowed

    if is_insider:
        products = Product.objects.filter(team=team)
    else:
        visibilities = (
            (Component.Visibility.PUBLIC, Component.Visibility.GATED)
            if has_gated_grant
            else (Component.Visibility.PUBLIC,)
        )
        products = Product.objects.filter(team=team, is_public=True, components__visibility__in=visibilities)

    return ViewerScope(
        has_gated_grant=has_gated_grant,
        product_ids=frozenset(str(pk) for pk in products.values_list("id", flat=True).distinct()),
        is_authenticated=is_authenticated,
        is_insider=is_insider,
    )


def _readable_queryset(team: Any) -> Any:
    """Externally-visible advisories with the rows a public projection reads.

    Private advisories are excluded in SQL rather than in Python: they must not
    reach the process that renders the page, so a template bug cannot leak one.
    """
    return (
        SecurityAdvisory.objects.filter(team=team, status__in=_READABLE_STATUSES)
        .exclude(visibility=SecurityAdvisory.Visibility.PRIVATE)
        .prefetch_related(
            Prefetch("vulnerabilities", queryset=AdvisoryVulnerability.objects.order_by("cve_id")),
            Prefetch("products", queryset=AdvisoryProduct.objects.select_related("product")),
            Prefetch("references", queryset=AdvisoryReference.objects.order_by("reference_type")),
            # The list renders per-product version rows, not just the detail
            # page, so the status graph is prefetched for both. Without it every
            # row on a 25-advisory page costs a query per product status.
            "vulnerabilities__product_statuses__advisory_product__product",
            "vulnerabilities__product_statuses__version_ranges",
            Prefetch(
                "events",
                queryset=AdvisoryEvent.objects.filter(event_type__in=AdvisoryEvent.PUBLIC_EVENT_TYPES).order_by(
                    "created_at"
                ),
                to_attr="public_events",
            ),
        )
        # Newest disclosure first, which is the order a reader scans a feed in.
        # ``published_at`` rather than ``created_at``: when a workspace drafts an
        # advisory for weeks, the date that matters outside is the one it went out.
        .order_by("-published_at", "-created_at")
    )


def _visible_products(advisory: SecurityAdvisory, scope: ViewerScope) -> tuple[list[dict[str, Any]], int]:
    """Product chips the reader may see, plus a count of the ones withheld.

    An advisory can name several products, and passing the gate on one of them is
    not permission to learn the names of the others. Rows with no ``product`` FK
    are a workspace naming something it does not track in sbomify — there is no
    product to hold a permission against, so they are shown as plain text.
    """
    chips: list[dict[str, Any]] = []
    withheld = 0
    for advisory_product in advisory.products.all():
        product = advisory_product.product
        if product is not None and str(product.id) not in scope.product_ids:
            withheld += 1
            continue
        chips.append(
            {
                "key": advisory_product.id,
                "id": product.id if product else None,
                "slug": getattr(product, "slug", "") if product else "",
                "name": product.name if product else advisory_product.product_name,
            }
        )
    return chips, withheld


def _cvss_chips(entries: Any) -> list[dict[str, Any]]:
    """A vulnerability's scores as the detail chips render them.

    A hand-entered row can be malformed or carry no version; the label absorbs
    both ("CVSS 3.1" or plain "CVSS") so the template stays a flat loop.
    """
    chips: list[dict[str, Any]] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        try:
            score = float(entry["base_score"])
        except (KeyError, TypeError, ValueError):
            continue
        version = str(entry.get("version") or "").strip()
        chips.append(
            {
                "label": f"CVSS {version}" if version else "CVSS",
                "base_score": score,
                "version": version,
                "vector": str(entry.get("vector") or "").strip(),
            }
        )
    return chips


def _public_vulnerability(vulnerability: AdvisoryVulnerability) -> dict[str, Any]:
    return {
        "id": vulnerability.id,
        "cve_id": vulnerability.cve_id,
        "title": vulnerability.title,
        "description": vulnerability.description,
        "severity": vulnerability.severity,
        "cwe_ids": vulnerability.cwe_ids or [],
        "cvss_scores": _cvss_chips(vulnerability.cvss_scores),
        "exploitation_status": vulnerability.exploitation_status,
        "recommendation": vulnerability.recommendation,
    }


def _humanise(delta_from: Any, delta_to: Any = None) -> str:
    """A coarse, single-unit duration: "3 days", "2 months", or "" for none.

    ``django.utils.timesince`` returns two units ("2 days, 3 hours"), which is
    more precision than a disclosure timeline wants — the reader is asking "was
    this recent" and "did they leave it a while", not counting hours. Trimming
    to the leading unit keeps the entries scannable.

    Returns "" for a sub-minute duration (``timesince`` floors to minutes and
    renders "0 minutes"), leaving the caller to phrase it — "just now" and
    "moments later" are the same duration but not the same sentence.
    """
    if delta_from is None:
        return ""
    # timesince joins its number and unit with a non-breaking space, so a plain
    # " " comparison silently never matches.
    rendered = timesince(delta_from, delta_to).replace(" ", " ")
    leading = rendered.split(",")[0].strip()
    return "" if leading.startswith("0 ") else leading


def _age_phrase(moment: Any) -> str:
    """How long ago something happened, as a finished phrase."""
    if moment is None:
        return ""
    return f"{humanised} ago" if (humanised := _humanise(moment)) else "just now"


def _gap_phrase(earlier: Any, later: Any) -> str:
    """How long after the previous entry, as a finished phrase.

    Empty when there is no earlier entry to measure against — the oldest event
    is the start of the story, not a zero-length gap.
    """
    if earlier is None or later is None:
        return ""
    return f"{humanised} later" if (humanised := _humanise(earlier, later)) else "moments later"


def _public_event(event: AdvisoryEvent, *, previous: AdvisoryEvent | None = None) -> dict[str, Any]:
    """One timeline entry: what happened, when, and how long after the last one.

    The workspace timeline renders an actor and a raw payload. Neither belongs on
    a public page: the actor names an employee, and a ``field_change`` payload
    carries the old value, which is the thing an embargo existed to withhold.
    ``_readable_queryset`` has already dropped every event type outside
    ``PUBLIC_EVENT_TYPES``, so this only has to shape what survived.

    ``previous`` is the next *older* event, which is what the gap is measured
    against — "11 days later" is the number that tells a reader whether a vendor
    kept them posted or went quiet, and it cannot be read off two absolute dates
    at a glance.
    """
    payload = event.payload if isinstance(event.payload, dict) else {}
    to_status = payload.get("to") if event.event_type == AdvisoryEvent.EventType.STATUS_CHANGE else None
    # A status change borrows the icon of the state it moved *to*, so the rail
    # reads as the remediation story. Everything else has its own icon.
    meta = REMEDIATION_META.get(to_status or "", {}) if to_status else {}
    fallback = EVENT_META.get(event.event_type, _DEFAULT_EVENT_META)
    return {
        "id": event.id,
        "kind": event.event_type,
        "label": meta.get("label") or fallback["label"],
        "variant": meta.get("variant") or fallback["variant"],
        "icon": meta.get("icon") or fallback["icon"],
        "note": event.body,
        # Three complementary readings of the same instant: the date to cite,
        # the time for same-day ordering, and the relative age to feel.
        "date_display": display_date(event.created_at),
        "time_display": f"{event.created_at:%H:%M}",
        "age": _age_phrase(event.created_at),
        "gap": _gap_phrase(previous.created_at if previous is not None else None, event.created_at),
        "created_at": event.created_at,
    }


def _version_expressions(status: AdvisoryProductStatus) -> tuple[str, str]:
    """Render one product status as the ("affected", "unaffected") pair a table shows.

    A vendor advisory index is read version-first — "am I on a version that is
    affected, and what do I move to" — so the stored range endpoints are turned
    into the comparison strings that question is answered in, rather than the
    raw ``[a, b)`` interval notation the model's ``__str__`` uses.

    A suppressing status short-circuits: "not affected" means no version is,
    which no range can express and every range would obscure.
    """
    if status.status in AdvisoryProductStatus.SUPPRESSING_STATES:
        return "None", "All"

    affected: list[str] = []
    unaffected: list[str] = []
    for version_range in status.version_ranges.all():
        introduced = version_range.introduced
        fixed = version_range.fixed
        last = version_range.last_affected

        if fixed:
            affected.append(f">= {introduced}, < {fixed}" if introduced else f"< {fixed}")
            unaffected.append(f">= {fixed}")
        elif last:
            affected.append(f">= {introduced}, <= {last}" if introduced else f"<= {last}")
            unaffected.append(f"> {last}")
        elif introduced:
            # Open-ended: everything from here up is affected, so there is no
            # unaffected version to name yet.
            affected.append(f">= {introduced}")

    # No ranges recorded, but a fix was named — that is enough to answer the
    # question, and it is the common shape for an advisory written in a hurry.
    if not affected and status.recommended_version:
        affected.append(f"< {status.recommended_version}")
        unaffected.append(f">= {status.recommended_version}")

    return ", ".join(affected) or "—", ", ".join(unaffected) or "—"


def _affected_rows(advisory: SecurityAdvisory, scope: ViewerScope) -> list[dict[str, Any]]:
    """One table sub-row per product the advisory speaks about.

    This is the shape the list renders: a single advisory occupies several rows,
    one per product, with the CVSS and summary cells spanning them. Rows for
    products the reader cannot see are dropped here for the same reason their
    chips are — passing the gate on one product is not permission to learn the
    others.
    """
    rows: list[dict[str, Any]] = []
    for vulnerability in advisory.vulnerabilities.all():
        for status in vulnerability.product_statuses.all():
            advisory_product = status.advisory_product
            product = advisory_product.product if advisory_product else None
            if product is not None and str(product.id) not in scope.product_ids:
                continue
            if advisory_product is None:
                label = "All products"
            else:
                label = advisory_product.product_name or (product.name if product else "")
            affected, unaffected = _version_expressions(status)
            rows.append(
                {
                    "product": label,
                    "affected": affected,
                    "unaffected": unaffected,
                    "status": status.status,
                    "status_label": status.get_status_display(),
                    "status_variant": STATUS_VARIANTS.get(status.status, "secondary"),
                }
            )
    return rows


def _cvss_score(advisory: SecurityAdvisory) -> float | None:
    """The worst CVSS base score across the advisory's vulnerabilities.

    The index leads with a number, and an advisory carrying three CVEs must not
    read as the mildest of them. Returns None when nobody scored it, which the
    template renders as a dash rather than a misleading 0.0.
    """
    entry = worst_cvss(advisory)
    return float(entry["base_score"]) if entry else None


def _public_projection(advisory: SecurityAdvisory, scope: ViewerScope, *, detail: bool = False) -> dict[str, Any]:
    severity = worst_severity(advisory)
    remediation = REMEDIATION_META.get(advisory.remediation_status, {})
    vulnerabilities = list(advisory.vulnerabilities.all())
    # ``public_events`` is the to_attr from _readable_queryset; falling back to
    # the relation keeps the function usable on an advisory fetched some other
    # way, filtering by hand so the fallback cannot be the leaky path.
    events = getattr(advisory, "public_events", None)
    if events is None:
        events = [e for e in advisory.events.all() if e.event_type in AdvisoryEvent.PUBLIC_EVENT_TYPES]
    products, withheld = _visible_products(advisory, scope)
    updated_at = max((e.created_at for e in events), default=advisory.published_at or advisory.updated_at)

    projection: dict[str, Any] = {
        "id": str(display_id(advisory)),
        "pk": str(advisory.id),
        "title": advisory.title,
        "summary": advisory.summary,
        "description": advisory.description,
        "severity": severity,
        "severity_label": severity.title() if severity else "Unrated",
        "severity_rank": SEVERITY_RANK.get(severity, 0),
        "status": advisory.remediation_status,
        "status_label": remediation.get("label", ""),
        "status_variant": remediation.get("variant", "secondary"),
        "status_icon": remediation.get("icon", "fas fa-circle"),
        "is_open": advisory.remediation_status not in SecurityAdvisory.CLOSED_REMEDIATION_STATUSES,
        "publication_status": advisory.status,
        "publication_label": advisory.get_status_display(),
        "publication_variant": PUBLICATION_VARIANTS.get(advisory.status, "secondary"),
        "is_withdrawn": advisory.status == SecurityAdvisory.Status.WITHDRAWN,
        "withdrawal_reason": advisory.withdrawal_reason,
        # The reader is told an advisory is restricted, not that it is theirs:
        # the badge explains why a colleague without the grant cannot see it.
        "visibility": advisory.visibility,
        "is_gated": advisory.visibility == SecurityAdvisory.Visibility.GATED,
        "products": products,
        "withheld_product_count": withheld,
        "vulnerability_count": len(vulnerabilities),
        "cve_ids": [v.cve_id for v in vulnerabilities if v.cve_id],
        "updates_count": len(events),
        "published_at": advisory.published_at,
        "published_display": display_date(advisory.published_at),
        "updated_at": updated_at,
        "updated_display": display_date(updated_at),
        # "Last updated 11 days ago" is the freshness signal a reader checks
        # before trusting the status above it.
        "updated_age": _age_phrase(updated_at),
        "published_age": _age_phrase(advisory.published_at),
        # The index columns: a score to sort and scan by, and the per-product
        # version rows the advisory spans.
        "cvss_score": _cvss_score(advisory),
        "affected_rows": _affected_rows(advisory, scope),
    }

    if detail:
        projection["vulnerabilities"] = [_public_vulnerability(v) for v in vulnerabilities]
        projection["references"] = [
            {
                "id": r.id,
                "type": r.reference_type,
                "external_id": r.external_id,
                "url": r.url,
                "summary": r.summary,
                "category": r.category,
            }
            for r in advisory.references.all()
        ]
        # Newest first, which is what a reader checking "where is this now"
        # wants. Each entry's gap is measured against the next *older* one, so
        # the pairing walks the reversed list one step behind.
        newest_first = sorted(events, key=lambda e: e.created_at, reverse=True)
        projection["timeline"] = [
            _public_event(event, previous=newest_first[index + 1] if index + 1 < len(newest_first) else None)
            for index, event in enumerate(newest_first)
        ]
        projection["acknowledgments"] = advisory.acknowledgments or []
        projection["statuses"] = _public_statuses(advisory, scope)
    return projection


def _public_statuses(advisory: SecurityAdvisory, scope: ViewerScope) -> list[dict[str, Any]]:
    """The "is my version affected" table: one row per vulnerability x product.

    Rows for products the reader may not see are dropped for the same reason
    their chips are, and a portfolio-wide row (``advisory_product`` NULL) is kept
    because it names nothing.
    """
    rows: list[dict[str, Any]] = []
    for vulnerability in advisory.vulnerabilities.all():
        for status in vulnerability.product_statuses.all():
            advisory_product = status.advisory_product
            product = advisory_product.product if advisory_product else None
            if product is not None and str(product.id) not in scope.product_ids:
                continue
            if advisory_product is None:
                scope_label = "All products"
            else:
                scope_label = advisory_product.product_name or (product.name if product else "")
            affected, unaffected = _version_expressions(status)
            rows.append(
                {
                    "id": status.id,
                    "vulnerability": vulnerability.cve_id or vulnerability.title,
                    "product": scope_label,
                    "product_id": product.id if product else None,
                    # The version expressions the index shows, so a machine
                    # reader gets the same answer as the table.
                    "affected": affected,
                    "unaffected": unaffected,
                    "status": status.status,
                    "status_label": status.get_status_display(),
                    "status_variant": STATUS_VARIANTS.get(status.status, "secondary"),
                    "justification": status.get_justification_display() if status.justification else "",
                    "justification_value": status.justification,
                    "impact_statement": status.impact_statement,
                    "action_statement": status.action_statement,
                    "response": status.response,
                    "recommended_version": status.recommended_version,
                    "version_ranges": [str(r) for r in status.version_ranges.all()],
                }
            )
    return rows


def list_public_advisories(
    request: Any, team: Any, *, limit: int | None = None, search: str = ""
) -> ServiceResult[dict[str, Any]]:
    """Advisories this reader may see, newest disclosure first.

    Returns the rows plus the two numbers the page needs to be honest about what
    it is not showing: how many gated advisories were filtered out, and whether
    logging in could change that. Saying "3 advisories are restricted" is the
    point of a gated trust center — a reader who cannot tell restricted content
    exists cannot ask for it.
    """
    scope = resolve_viewer_scope(request, team)

    queryset = _readable_queryset(team)
    if search := (search or "").strip():
        queryset = queryset.filter(
            Q(title__icontains=search) | Q(tracking_id__icontains=search) | Q(vulnerabilities__cve_id__icontains=search)
        ).distinct()

    visible: list[dict[str, Any]] = []
    hidden = 0
    for advisory in queryset:
        product_ids = frozenset(str(p.product_id) for p in advisory.products.all() if p.product_id is not None)
        if scope.may_read(advisory.visibility, product_ids):
            visible.append(_public_projection(advisory, scope))
        else:
            hidden += 1

    total = len(visible)
    if limit is not None:
        visible = visible[:limit]

    return ServiceResult.success(
        {
            "advisories": visible,
            "total": total,
            "hidden_count": hidden,
            # An anonymous reader may just need to log in; a logged-in reader
            # without the grant needs to request access. The page words its
            # prompt from this rather than guessing.
            "viewer_is_authenticated": scope.is_authenticated,
            "viewer_has_gated_grant": scope.has_gated_grant,
        }
    )


@dataclass(frozen=True)
class AdvisoryQuery:
    """What the reader asked the index for.

    Built from query parameters by :func:`parse_advisory_query`, so the view
    does no parsing and an out-of-range page or a bogus severity cannot reach
    the filtering code.
    """

    search: str = ""
    severities: frozenset[str] = frozenset()
    products: frozenset[str] = frozenset()
    published_from: date | None = None
    published_to: date | None = None
    sort: str = SORT_NEWEST
    page: int = 1
    per_page: int = DEFAULT_PER_PAGE

    @property
    def is_filtered(self) -> bool:
        """Whether anything narrows the list — drives the "Clear" control."""
        return bool(self.search or self.severities or self.products or self.published_from or self.published_to)

    @property
    def active_count(self) -> int:
        """How many filters are on.

        Shown on the mobile toggle, where the panel is collapsed and the count
        is the only sign that the list is narrowed. Each ticked box counts
        separately, and the date range counts as one per endpoint, because that
        is what the reader would have to undo.
        """
        return (
            len(self.severities)
            + len(self.products)
            + bool(self.search)
            + bool(self.published_from)
            + bool(self.published_to)
        )


def _parse_date(value: str | None) -> date | None:
    """A ``YYYY-MM-DD`` date input value, or None for anything unparseable.

    Silent rather than raising: this is a public page, and a hand-edited query
    string should drop the filter, not 500.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def parse_advisory_query(params: Any) -> AdvisoryQuery:
    """Turn a ``request.GET`` into a validated :class:`AdvisoryQuery`.

    Unknown severities are dropped rather than passed through, so the filter set
    can only ever be a subset of the vocabulary the facets offer.
    """
    try:
        page = max(1, int(params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1

    severities = frozenset(params.getlist("severity")) & frozenset(SEVERITY_ORDER)
    sort = params.get("sort", SORT_NEWEST)
    return AdvisoryQuery(
        search=(params.get("search") or "").strip(),
        severities=severities,
        products=frozenset(p for p in params.getlist("product") if p),
        published_from=_parse_date(params.get("from")),
        published_to=_parse_date(params.get("to")),
        sort=sort if sort in SORT_OPTIONS else SORT_NEWEST,
        page=page,
    )


def _matches(advisory: dict[str, Any], query: AdvisoryQuery) -> bool:
    """Does one projected advisory survive the sidebar filters?

    Applied in Python rather than SQL because the rows have already been through
    the visibility filter, which is itself per-row. Re-expressing the filters as
    a second database query would let the two disagree about the same advisory —
    and the facet counts beside them are built from this same list, so a count
    could then name a row the table does not show.
    """
    if query.severities and advisory["severity"] not in query.severities:
        return False
    if query.products:
        names = {p["name"] for p in advisory["products"]}
        if not (names & query.products):
            return False
    published = advisory["published_at"]
    if query.published_from and (published is None or published.date() < query.published_from):
        return False
    if query.published_to and (published is None or published.date() > query.published_to):
        return False
    return True


def _facets(advisories: list[dict[str, Any]], query: AdvisoryQuery) -> dict[str, list[dict[str, Any]]]:
    """Sidebar counts, built from the rows the reader may see.

    Each facet is counted against the list filtered by *every other* facet, the
    usual faceted-search rule: ticking a second severity must widen the result,
    so the severity counts cannot themselves be narrowed by the severity filter.
    """
    severity_pool = [a for a in advisories if _matches(a, replace(query, severities=frozenset()))]
    product_pool = [a for a in advisories if _matches(a, replace(query, products=frozenset()))]

    severity_counts = Counter(a["severity"] or "none" for a in severity_pool)
    product_counts: Counter[str] = Counter()
    for advisory in product_pool:
        for product in advisory["products"]:
            product_counts[product["name"]] += 1

    return {
        "severity": [
            {
                "value": value,
                "label": SEVERITY_LABELS[value],
                "count": severity_counts.get(value, 0),
                "checked": value in query.severities,
            }
            for value in SEVERITY_ORDER
        ],
        "product": [
            {"value": name, "label": name, "count": count, "checked": name in query.products}
            for name, count in sorted(product_counts.items())
        ],
    }


def _sorted(advisories: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    """Order the page. ``_readable_queryset`` already returns newest-first."""
    if sort == SORT_OLDEST:
        return list(reversed(advisories))
    if sort == SORT_SEVERITY:
        # Severity first, then newest within a severity, so the top of the page
        # is "the worst thing, most recently". ``cvss_score`` breaks ties inside
        # a band, since two "high" advisories are not equally high.
        return sorted(
            advisories,
            key=lambda a: (a["severity_rank"], a["cvss_score"] or 0, a["published_at"] or _EPOCH),
            reverse=True,
        )
    return advisories


def browse_public_advisories(request: Any, team: Any, query: AdvisoryQuery) -> ServiceResult[dict[str, Any]]:
    """The advisory index: filtered, faceted, sorted and paginated.

    Layered on :func:`list_public_advisories` rather than reimplementing it, so
    the index and the landing page's panel resolve visibility identically.
    """
    base = list_public_advisories(request, team, search=query.search).value or {}
    visible: list[dict[str, Any]] = base.get("advisories", [])

    facets = _facets(visible, query)
    matching = _sorted([a for a in visible if _matches(a, query)], query.sort)

    total = len(matching)
    page_count = max(1, ceil(total / query.per_page))
    page = min(query.page, page_count)
    start = (page - 1) * query.per_page
    rows = matching[start : start + query.per_page]

    return ServiceResult.success(
        {
            "advisories": rows,
            "total": total,
            "unfiltered_total": len(visible),
            "hidden_count": base.get("hidden_count", 0),
            "viewer_is_authenticated": base.get("viewer_is_authenticated", False),
            "viewer_has_gated_grant": base.get("viewer_has_gated_grant", False),
            "facets": facets,
            "query": query,
            "sort_options": [
                {"value": value, "label": label, "selected": value == query.sort}
                for value, label in SORT_OPTIONS.items()
            ],
            "page": page,
            "page_count": page_count,
            "per_page": query.per_page,
            # 1-indexed and inclusive, matching the "1 - 25 of 551" the header shows.
            "start_index": start + 1 if rows else 0,
            "end_index": start + len(rows),
            "has_prev": page > 1,
            "has_next": page < page_count,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
    )


def get_public_advisory(request: Any, team: Any, advisory_id: str) -> ServiceResult[dict[str, Any]]:
    """One advisory, or a 404 the reader cannot distinguish from "does not exist".

    A gated advisory the reader may not see returns 404 rather than 403 on
    purpose: a 403 confirms that an advisory with that id exists for this
    workspace, which is exactly the fact an embargo is keeping.
    """
    scope = resolve_viewer_scope(request, team)
    advisory = _readable_queryset(team).filter(Q(id=advisory_id) | Q(tracking_id=advisory_id)).first()
    if advisory is None:
        return ServiceResult.failure("Advisory not found", status_code=404)

    product_ids = frozenset(str(p.product_id) for p in advisory.products.all() if p.product_id is not None)
    if not scope.may_read(advisory.visibility, product_ids):
        return ServiceResult.failure("Advisory not found", status_code=404)

    return ServiceResult.success(_public_projection(advisory, scope, detail=True))


def public_advisory_summary(request: Any, team: Any, *, limit: int = 3) -> dict[str, Any]:
    """The landing page's advisory panel: a few recent rows and the tallies.

    A thin wrapper so the trust-center home and the advisories page cannot
    disagree about who may read what.
    """
    result = list_public_advisories(request, team, limit=limit)
    payload = result.value or {}
    advisories = payload.get("advisories", [])
    return {
        "recent": advisories,
        "total": payload.get("total", 0),
        "open_count": sum(1 for a in advisories if a["is_open"]),
        "hidden_count": payload.get("hidden_count", 0),
        "viewer_is_authenticated": payload.get("viewer_is_authenticated", False),
        "viewer_has_gated_grant": payload.get("viewer_has_gated_grant", False),
        "latest_display": advisories[0]["published_display"] if advisories else "",
    }
