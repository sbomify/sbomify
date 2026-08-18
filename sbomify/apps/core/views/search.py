from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.views import View

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.posthog_service import capture_for_request
from sbomify.apps.core.spotlight import ASSET_BASE_SCORE, SECTION_LABELS, search_destinations
from sbomify.apps.core.utils import get_team_id_from_session
from sbomify.apps.teams.permissions import GuestAccessBlockedMixin


class SearchView(GuestAccessBlockedMixin, LoginRequiredMixin, View):
    """Spotlight search: app destinations first, then the workspace's assets.

    Navigation is the primary job. Someone typing here usually wants to *go*
    somewhere — settings, tokens, the plugins page — so destinations from
    ``spotlight.py`` lead, and the workspace's own records fill the tail.

    ``products``/``components`` are the legacy keys the older dropdown reads
    and cover assets only. ``results`` is the flat, ranked palette list and is
    a superset: it also carries navigation destinations, advisories, findings,
    releases and documents. They are not interchangeable.
    """

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """Answer a redirect with JSON, but not the same JSON for both of them.

        Two mixins can redirect here, and a fetch cannot follow either: the
        client would parse an HTML document as JSON and surface a generic
        failure.

        ``GuestAccessBlockedMixin`` bounces a guest to the public workspace
        page. There genuinely is no workspace data for them, so an empty result
        set in the shape the client expects is a true answer.

        ``LoginRequiredMixin`` bounces an unauthenticated caller to the login
        page — including a session that expired mid-typing. Answering *that*
        with an empty result set tells the user their workspace is empty, which
        is false, and hides the one thing they need to know. It is a 401, which
        the client turns into a prompt to sign in again.
        """
        response = super().dispatch(request, *args, **kwargs)
        if (
            getattr(response, "status_code", None) not in (301, 302)
            or request.headers.get("X-Requested-With") != "XMLHttpRequest"
        ):
            return response
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Authentication required", "authenticated": False}, status=401)
        return JsonResponse({"products": [], "components": [], "results": []})

    def get(self, request: HttpRequest) -> JsonResponse:
        query = request.GET.get("q", "").strip()
        try:
            limit = max(1, min(int(request.GET.get("limit", 10)), 50))
        except (ValueError, TypeError):
            limit = 10

        if not query or len(query) < 2:
            return JsonResponse({"products": [], "components": [], "results": []})

        current_team = request.session.get("current_team") or {}
        destinations = search_destinations(
            query,
            # ``or ""`` rather than a get() default: the session stores role=None for a
            # workspace whose membership carries none, and a default only fires on a
            # missing key. search_destinations is typed str.
            role=current_team.get("role") or "",
            team_key=current_team.get("key", ""),
        )

        team_id = get_team_id_from_session(request)
        if not team_id:
            # No workspace in session still gets the navigation half — the
            # palette's main job does not depend on having picked a workspace.
            return JsonResponse({"products": [], "components": [], "results": destinations})

        product_search_filter = Q(name__icontains=query) | Q(description__icontains=query)
        name_search_filter = Q(name__icontains=query)

        products = Product.objects.filter(team_id=team_id).filter(product_search_filter).order_by("name")[:limit]
        products_data = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description or "",
                "is_public": p.is_public,
            }
            for p in products
        ]

        components = Component.objects.filter(team_id=team_id).filter(name_search_filter).order_by("name")[:limit]
        components_data = [
            {
                "id": c.id,
                "name": c.name,
                "description": "",
                "visibility": c.visibility,
                "component_type": c.component_type or "",
            }
            for c in components
        ]

        # Empty team_key here means the session is missing the
        # ``current_team`` shape; ``capture_for_request`` will skip the
        # event entirely rather than mis-attribute it to a user PK (see
        # the empty-string branch in posthog_service.capture_for_request).
        # This is preferred over silently turning a workspace-scoped
        # event into a user-scoped one.
        team_key = current_team.get("key", "")
        result_count = len(products_data) + len(components_data)
        # NEVER include the raw ``query`` string in the event payload — it can
        # contain customer identifiers, internal component names, or secrets
        # users accidentally paste into the search bar. Ship the length and
        # result count only; if someone wants per-query analytics, that's a
        # separate consent-gated funnel, not a property on this event.
        capture_for_request(
            request,
            "search:performed",
            {
                "query_length": len(query),
                "result_count": result_count,
                "destination_count": len(destinations),
            },
            team_key=team_key,
        )

        return JsonResponse(
            {
                "products": products_data,
                "components": components_data,
                "results": destinations
                + _entity_results(query, team_id, limit)
                + _asset_results(products_data, components_data),
            }
        )


# ---------------------------------------------------------------------------
# Entity search — the "find my stuff" half of the palette.
#
# ADDING AN ENTITY TYPE: append one entry here. Each is
#   (section, label-icon, queryset factory, row -> (title, url)).
# The section must exist in spotlight.SECTION_ORDER so it sorts predictably.
# Everything scores at ASSET_BASE_SCORE, below every app destination, so a
# product named "Billing" can never outrank the billing page.
#
# Deliberately NOT here: package/dependency search ("which components ship
# log4j?"). Answering it means reading every SBOM's component list out of
# object storage per keystroke, which is a background index, not a query —
# worth building, but not behind a 200ms debounce.
# ---------------------------------------------------------------------------


def _advisory_rows(query: str, team_id: Any, limit: int) -> Any:
    from sbomify.apps.security_advisories.models import SecurityAdvisory

    return (
        SecurityAdvisory.objects.filter(team_id=team_id)
        .filter(
            Q(title__icontains=query) | Q(tracking_id__icontains=query) | Q(vulnerabilities__cve_id__icontains=query)
        )
        .distinct()
        .order_by("-updated_at")[:limit]
    )


def _finding_rows(query: str, team_id: Any, limit: int) -> Any:
    """Open findings only: a resolved one is history, and leading with it
    would answer "am I affected?" wrongly.

    Matched on the component's name as well as the advisory id. The row already
    reads "CVE-x in component-y", so someone typing the component name and
    getting nothing was being told that component has no open findings.
    """
    from sbomify.apps.plugins.models import VulnerabilityLifecycle

    return (
        VulnerabilityLifecycle.objects.filter(component__team_id=team_id, resolved_at__isnull=True)
        .filter(Q(advisory_id__icontains=query) | Q(component__name__icontains=query))
        .select_related("component")
        .order_by("advisory_id", "component__name")[:limit]
    )


def _release_rows(query: str, team_id: Any, limit: int) -> Any:
    from sbomify.apps.core.models import Release

    return (
        Release.objects.filter(product__team_id=team_id)
        .filter(Q(name__icontains=query) | Q(version__icontains=query))
        .select_related("product")
        .order_by("-created_at")[:limit]
    )


def _document_rows(query: str, team_id: Any, limit: int) -> Any:
    from sbomify.apps.documents.models import Document

    return (
        Document.objects.filter(component__team_id=team_id, name__icontains=query)
        .select_related("component")
        .order_by("-created_at")[:limit]
    )


ENTITY_SEARCHES: tuple[tuple[str, str, Any, Any], ...] = (
    (
        "advisories",
        "fa-shield-halved",
        _advisory_rows,
        # Title first. The identifier is long enough to eat the row on its own,
        # and leading with it meant the half that got truncated away was the
        # readable one, which is the half someone scans for.
        lambda row: (
            f"{row.title} · {row.tracking_id or row.id}",
            reverse("core:security_advisory_detail", kwargs={"advisory_id": row.id}),
        ),
    ),
    (
        "findings",
        "fa-bug",
        _finding_rows,
        lambda row: (
            f"{row.advisory_id}{f' · {row.severity}' if row.severity else ''} · {row.component.name}",
            reverse("core:component_details", kwargs={"component_id": row.component_id}),
        ),
    ),
    (
        "releases",
        "fa-tag",
        _release_rows,
        lambda row: (
            f"{row.version or row.name} · {row.product.name}",
            reverse("core:release_details", kwargs={"product_id": row.product_id, "release_id": row.id}),
        ),
    ),
    (
        "documents",
        "fa-file-lines",
        _document_rows,
        lambda row: (
            f"{row.name} · {row.component.name}",
            reverse("core:component_details", kwargs={"component_id": row.component_id}),
        ),
    ),
)


def _entity_results(query: str, team_id: Any, limit: int) -> list[dict[str, Any]]:
    """Every entity type's matches, in ENTITY_SEARCHES order."""
    results: list[dict[str, Any]] = []
    for section, icon, rows_for, to_row in ENTITY_SEARCHES:
        seen: set[str] = set()
        for row in rows_for(query, team_id, limit):
            title, url = to_row(row)
            # The same CVE can be recorded by several scanners, and a
            # release can repeat a version across products.
            if title in seen:
                continue
            seen.add(title)
            results.append(
                {
                    "title": title,
                    "url": url,
                    "section": section,
                    "section_label": SECTION_LABELS.get(section, section.title()),
                    "icon": icon,
                    "score": ASSET_BASE_SCORE,
                }
            )
    return results


def _asset_results(products: list[dict[str, Any]], components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assets in the flat palette shape, ranked below every destination.

    A product literally named "Settings" must not outrank the Settings page
    for someone typing "settings", which is why the score is a constant floor
    rather than a computed relevance.
    """
    label = SECTION_LABELS["assets"]
    rows = [
        {
            "title": product["name"],
            "url": reverse("core:product_details", kwargs={"product_id": product["id"]}),
            "section": "assets",
            "section_label": label,
            "icon": "fa-cube",
            "score": ASSET_BASE_SCORE,
        }
        for product in products
    ]
    rows += [
        {
            "title": component["name"],
            "url": reverse("core:component_details", kwargs={"component_id": component["id"]}),
            "section": "assets",
            "section_label": label,
            "icon": "fa-puzzle-piece",
            "score": ASSET_BASE_SCORE,
        }
        for component in components
    ]
    return rows
