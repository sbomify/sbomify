"""Workspace inventory for the Products area, including its release and component views."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest
from django.urls import reverse

from sbomify.apps.core.authz import can
from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.services.security_snapshot import build_component_security_picture
from sbomify.apps.sboms.freshness import freshness_state
from sbomify.apps.sboms.models import ProductComponent
from sbomify.apps.teams.models import Team
from sbomify.apps.vulnerability_scanning.posture import build_release_vuln_postures

KINDS = ("products", "releases", "components")
SEVERITIES = ("total", "critical", "high", "medium", "low")
# One page holds the three kinds, so the page has to say which one it is
# holding: the browser title that a bookmark and a row of open tabs read, and
# the heading above the table. The tab row alone cannot carry that.
HEADINGS = {
    "products": ("Products", "Everything this workspace ships, and the evidence behind it."),
    "components": ("Components", "Every component this workspace maintains, and the evidence behind it."),
    "releases": ("Releases", "Every release across this workspace, and what each one ships."),
}
# Each kind opens on the order its readers want. A product or component list is
# a catalogue, read by name; a release list is a history, read newest first.
# Alphabetical order there puts v10.0.0 above v2.0.0 and scatters the rolling
# `latest` rows through the versions.
DEFAULT_ORDER = {
    "products": ("name", "asc"),
    "components": ("name", "asc"),
    "releases": ("created_at", "desc"),
}
COLUMNS = {
    "products": (
        ("name", "Product"),
        ("release_count", "Releases"),
        ("vulnerabilities", "Vulnerabilities"),
        ("past_sla", "Past SLA"),
        ("stale", "Evidence"),
        ("visibility", "Visibility"),
        ("created_at", "Created at"),
    ),
    "releases": (
        ("name", "Release"),
        ("artifact_count", "Artifacts"),
        ("vulnerabilities", "Vulnerabilities"),
        ("collection_version", "Collection"),
        ("visibility", "Visibility"),
        ("release_type", "Type"),
        ("created_at", "Created at"),
    ),
    "components": (
        ("name", "Component"),
        ("artifact_count", "Artifacts"),
        ("freshness_label", "Freshness"),
        ("scan_label", "Scan"),
        ("vulnerabilities", "Vulnerabilities"),
        ("visibility", "Visibility"),
        ("created_at", "Created at"),
    ),
}


def _counts(counts: dict[str, int] | None = None) -> dict[str, int]:
    result = {key: (counts or {}).get(key, 0) for key in SEVERITIES}
    result["unknown"] = result["total"] - sum(result[key] for key in ("critical", "high", "medium", "low"))
    result["other"] = result["total"] - result["critical"] - result["high"]
    return result


def _visibility_options(kind: str) -> tuple[str, ...]:
    return ("all", "public", "private", "gated") if kind == "components" else ("all", "public", "private")


def _url(params: dict[str, Any], *, base_url: str = "", **changes: Any) -> str:
    query = urlencode({key: value for key, value in {**params, **changes}.items() if value != ""})
    return (base_url or reverse("core:products_dashboard")) + (f"?{query}" if query else "")


def _scope_counts(workspace: Team, product_id: str = "") -> dict[str, int]:
    products = Product.objects.filter(team=workspace)
    components = Component.objects.filter(team=workspace)
    releases = Release.objects.filter(product__team=workspace)
    if product_id:
        products = products.filter(id=product_id)
        components = components.filter(products__id=product_id)
        releases = releases.filter(product_id=product_id)
    return {"products": products.count(), "components": components.count(), "releases": releases.count()}


def _tab_href(params: dict[str, Any], kind: str, target: str) -> str:
    """Carry the slice the user built, drop what belongs to the list they typed it into.

    Risk, visibility, ordering and page size describe the same question asked of
    three kinds, so a tab switch keeps them; search and the page number describe
    one list and are left behind. Anything the target kind cannot honour, a
    gated visibility outside components or a sort key it has no column for, is
    dropped here rather than silently reset on arrival.
    """
    sort, direction = params["sort"], params["direction"]
    if (sort, direction) == DEFAULT_ORDER[kind] or sort not in dict(COLUMNS[target]):
        sort = direction = ""
    return _url(
        {
            "product": params["product"] if target != "products" and params["product"] != "unassigned" else "",
            "risk": params["risk"] if params["risk"] != "all" else "",
            "visibility": params["visibility"] if params["visibility"] in _visibility_options(target)[1:] else "",
            "sort": sort,
            "direction": direction,
            "per_page": params["per_page"] if params["per_page"] != "10" else "",
        },
        base_url=reverse(f"core:{target}_dashboard"),
    )


def _inventory_catalog(workspace: Team, product_id: str = "") -> dict[str, Any]:
    products = Product.objects.filter(team=workspace)
    if product_id:
        products = products.filter(id=product_id)
    return {
        "products": list(products.order_by("name", "id").values("id", "name")),
        "counts": _scope_counts(workspace, product_id),
    }


def build_inventory_snapshot(
    workspace: Team,
    kind: str,
    *,
    product_id: str = "",
    row_ids: list[str] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hydrate selected rows, retaining the authorised scope's tab counts."""
    catalog = catalog if catalog is not None else _inventory_catalog(workspace, product_id)
    component_scope = Q(products__id=product_id) if product_id else Q()
    product_scope = Q(id=product_id) if product_id else Q()
    release_scope = Q(product_id=product_id) if product_id else Q()
    component_query = Component.objects.filter(component_scope, team=workspace)
    product_query = Product.objects.filter(product_scope, team=workspace).order_by("name", "id")
    release_query = Release.objects.filter(release_scope, product__team=workspace)
    if row_ids is not None:
        if kind == "products":
            product_query = product_query.filter(id__in=row_ids)
            component_query = component_query.filter(products__id__in=row_ids).distinct()
        elif kind == "components":
            component_query = component_query.filter(id__in=row_ids)
        else:
            release_query = release_query.filter(id__in=row_ids)
    components = (
        list(
            component_query.annotate(
                sbom_count=Count("sbom", distinct=True), document_count=Count("document", distinct=True)
            ).order_by("name", "id")
        )
        if kind != "releases"
        else []
    )
    products = []
    if kind == "products":
        products = list(
            product_query.annotate(release_count=Count("releases", distinct=True)).prefetch_related(
                Prefetch("components", queryset=Component.objects.filter(team=workspace).only("id"))
            )
        )
    tabs_count = catalog["counts"]
    choices = catalog["products"]
    memberships: dict[str, list[dict[str, str]]] = {}
    if kind == "components":
        links = ProductComponent.objects.filter(
            product__team=workspace, component_id__in=[component.id for component in components]
        )
        if product_id:
            links = links.filter(product_id=product_id)
        for link in links.order_by("product__name", "product_id").values("component_id", "product_id", "product__name"):
            memberships.setdefault(link["component_id"], []).append(
                {"id": link["product_id"], "name": link["product__name"]}
            )

    rows: list[dict[str, Any]] = []
    if kind == "releases":
        releases = list(
            release_query.select_related("product")
            .annotate(
                artifact_count=Count(
                    "artifacts",
                    filter=Q(artifacts__sbom__component__team=workspace)
                    | Q(artifacts__document__component__team=workspace),
                    distinct=True,
                )
            )
            .order_by("name", "id")
        )
        postures = build_release_vuln_postures(releases)
        for release in releases:
            posture = postures[release.id]
            counts = _counts(posture.get("counts"))
            rows.append(
                {
                    "id": release.id,
                    "name": release.name,
                    "description": release.description,
                    "released_at": release.released_at,
                    "version": release.version,
                    "is_latest": release.is_latest,
                    "is_prerelease": release.is_prerelease,
                    "release_date": release.released_at,
                    "product_id": release.product_id,
                    "product_name": release.product.name,
                    "product_ids": [release.product_id],
                    "counts": counts,
                    "vulnerabilities": counts["total"],
                    "unassessed": posture["unassessed"],
                    "assessed": posture.get("has_data", False),
                    "security_applicable": bool(posture.get("has_data") or posture["unassessed"]),
                    "artifact_count": release.artifact_count,
                    "collection_version": release.collection_version,
                    "visibility": "public" if release.product.is_public else "private",
                    "created_at": release.created_at,
                    "release_type": "Rolling latest"
                    if release.is_latest
                    else "Prerelease"
                    if release.is_prerelease
                    else "Release",
                    "url": reverse("core:release_details", args=[release.product_id, release.id]),
                }
            )
        return {"rows": rows, "counts": tabs_count, "products": choices}

    names = {component.id: component.name for component in components}
    picture = build_component_security_picture(list(names), names, workspace.patch_sla_days or {})
    overdue: dict[str, int] = {}
    for finding in picture["findings"]:
        if finding["sla"]["overdue"]:
            key = finding["component_id"]
            overdue[key] = overdue.get(key, 0) + 1
    component_rows = {}
    for component in components:
        latest = picture["latest_sboms"].get(component.id)
        days = component.sbom_freshness_days
        freshness = freshness_state(
            latest["created_at"] if latest else None, days if days is not None else workspace.sbom_freshness_days
        )
        counts = _counts(picture["counts"].get(component.id))
        assessed = component.id not in picture["unassessed"]
        is_document = component.component_type == Component.ComponentType.DOCUMENT
        stale = bool(freshness and freshness["is_stale"])
        freshness_label = (
            "Not applicable"
            if is_document
            else "No SBOM"
            if not latest
            else "No policy"
            if freshness is None
            else "Stale"
            if stale
            else "Current"
        )
        row = {
            "id": component.id,
            "name": component.name,
            "component_type": component.component_type,
            "products": memberships.get(component.id, []),
            "product_ids": [p["id"] for p in memberships.get(component.id, [])],
            "artifact_count": component.sbom_count + component.document_count,
            "has_sbom": bool(latest),
            "counts": counts,
            "vulnerabilities": counts["total"],
            "assessed": assessed,
            "security_applicable": not is_document,
            "unassessed": int(not assessed and not is_document),
            "last_scan": picture["last_scans"].get(component.id),
            "scan_label": "Not applicable"
            if is_document
            else "Scanned"
            if assessed
            else "Nothing scanned"
            if component.id in picture["last_scans"]
            else "Not assessed",
            "freshness_label": freshness_label,
            "stale": int(stale),
            "missing_sboms": int(not latest and not is_document),
            "past_sla": overdue.get(component.id, 0),
            "visibility": component.visibility,
            "created_at": component.created_at,
            "url": reverse("core:component_details", args=[component.id]),
        }
        component_rows[component.id] = row
    if kind == "components":
        rows = list(component_rows.values())
    else:
        for product in products:
            assigned = [component_rows[c.id] for c in product.components.all()]
            security_rows = [row for row in assigned if row["component_type"] != Component.ComponentType.DOCUMENT]
            counts = _counts({key: sum(row["counts"][key] for row in security_rows) for key in SEVERITIES})
            rows.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "description": product.description,
                    "component_count": len(assigned),
                    "security_component_count": len(security_rows),
                    "release_count": getattr(product, "release_count"),
                    "counts": counts,
                    "vulnerabilities": counts["total"],
                    "unassessed": sum(row["unassessed"] for row in security_rows),
                    "assessed": bool(security_rows) and all(row["assessed"] for row in security_rows),
                    "security_applicable": bool(security_rows),
                    "stale": sum(row["stale"] for row in security_rows),
                    "missing_sboms": sum(row["missing_sboms"] for row in security_rows),
                    "no_policy": sum(row["freshness_label"] == "No policy" for row in security_rows),
                    "past_sla": sum(row["past_sla"] for row in security_rows),
                    "visibility": "public" if product.is_public else "private",
                    "created_at": product.created_at,
                    "url": reverse("core:product_details", args=[product.id]),
                }
            )
    return {"rows": rows, "counts": tabs_count, "products": choices}


def build_inventory_context(request: HttpRequest, *, kind: str | None = None) -> ServiceResult[dict[str, Any]]:
    """Authorise the live membership before reading or filtering any inventory."""
    workspace_key = (request.session.get("current_team") or {}).get("key")
    workspace = Team.objects.filter(key=workspace_key).first() if workspace_key else None
    if workspace is None or not can(request, "workspace:read", workspace):
        return ServiceResult.failure("Workspace not found", status_code=404)
    kind = kind or request.GET.get("view", "products")
    if kind not in KINDS:
        kind = "products"
    return build_inventory_page(request, workspace, kind=kind)


def build_inventory_page(
    request: HttpRequest,
    workspace: Team,
    *,
    kind: str,
    product_id: str = "",
    base_url: str = "",
    content_id: str = "inventory-content",
) -> ServiceResult[dict[str, Any]]:
    """Select from cheap metadata before loading security details.

    Keep casefolded search and ordering identical to the shared table contract.
    Only risk filters and derived sort keys require security for every match.
    """
    catalog = _inventory_catalog(workspace, product_id)
    products = Product.objects.filter(team=workspace)
    components = Component.objects.filter(team=workspace)
    releases = Release.objects.filter(product__team=workspace)
    if product_id:
        products = products.filter(id=product_id)
        components = components.filter(products__id=product_id)
        releases = releases.filter(product_id=product_id)
    sort = request.GET.get("sort", "name")
    if kind == "products":
        fields = ["id", "name", "description", "created_at", "is_public"]
        if sort == "release_count":
            products = products.annotate(release_count=Count("releases"))
            fields.append("release_count")
        rows = list(products.values(*fields))
        for row in rows:
            row["visibility"] = "public" if row.pop("is_public") else "private"
            row["product_ids"] = []
    elif kind == "components":
        fields = ["id", "name", "created_at", "visibility"]
        if sort == "artifact_count":
            components = components.annotate(
                artifact_count=Count("sbom", distinct=True) + Count("document", distinct=True)
            )
            fields.append("artifact_count")
        rows = list(components.values(*fields))
        memberships: dict[str, list[dict[str, str]]] = {}
        links = ProductComponent.objects.filter(product__team=workspace, component__team=workspace)
        if product_id:
            links = links.filter(product_id=product_id)
        for link in links.order_by("product__name", "product_id").values("component_id", "product_id", "product__name"):
            memberships.setdefault(link["component_id"], []).append(
                {"id": link["product_id"], "name": link["product__name"]}
            )
        for row in rows:
            row["products"] = memberships.get(row["id"], [])
            row["product_ids"] = [product["id"] for product in row["products"]]
    else:
        fields = [
            "id",
            "name",
            "description",
            "created_at",
            "product_id",
            "product__name",
            "product__is_public",
            "collection_version",
            "is_latest",
            "is_prerelease",
        ]
        if sort == "artifact_count":
            releases = releases.annotate(
                artifact_count=Count(
                    "artifacts",
                    filter=Q(artifacts__sbom__component__team=workspace)
                    | Q(artifacts__document__component__team=workspace),
                    distinct=True,
                )
            )
            fields.append("artifact_count")
        rows = list(releases.values(*fields))
        for row in rows:
            row["product_name"] = row.pop("product__name")
            row["product_ids"] = [row["product_id"]]
            row["visibility"] = "public" if row.pop("product__is_public") else "private"
            row["release_type"] = (
                "Rolling latest" if row["is_latest"] else "Prerelease" if row["is_prerelease"] else "Release"
            )

    def hydrate(ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        detail_rows: list[dict[str, Any]] = build_inventory_snapshot(
            workspace, kind, product_id=product_id, row_ids=ids, catalog=catalog
        )["rows"]
        return detail_rows

    # One extra count query, and only while a product filter is actually on.
    filter_product = "" if kind == "products" else request.GET.get("product", "")
    tab_counts = _scope_counts(workspace, filter_product) if filter_product and filter_product != "unassigned" else None
    return build_inventory_table(
        request,
        {**catalog, "rows": rows},
        kind=kind,
        product_id=product_id,
        base_url=base_url,
        content_id=content_id,
        tab_counts=tab_counts,
        hydrate=hydrate,
    )


def build_inventory_table(
    request: HttpRequest,
    snapshot: dict[str, Any],
    *,
    kind: str,
    base_url: str = "",
    content_id: str = "inventory-content",
    product_id: str = "",
    tab_counts: dict[str, int] | None = None,
    hydrate: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> ServiceResult[dict[str, Any]]:
    """One server filter, sort and pagination contract for lists and detail pages.

    The caller authorises and scopes the snapshot before passing it here. A
    product scope is fixed by the route and cannot be widened by a query string.
    """
    base_url = base_url or reverse(f"core:{kind}_dashboard")
    default_sort, default_direction = DEFAULT_ORDER[kind]
    params: dict[str, Any] = {
        "search": request.GET.get("search", "").strip(),
        "risk": request.GET.get("risk", "all"),
        "visibility": request.GET.get("visibility", "all"),
        "product": product_id or (request.GET.get("product", "") if kind != "products" else ""),
        "sort": request.GET.get("sort", default_sort),
        "direction": request.GET.get("direction", default_direction),
        "per_page": request.GET.get("per_page", "10"),
    }
    if params["risk"] not in ("all", "attention", "clear", "unassessed"):
        params["risk"] = "all"
    visibility_options = _visibility_options(kind)
    if params["visibility"] not in visibility_options:
        params["visibility"] = "all"
    if params["sort"] not in dict(COLUMNS[kind]):
        params["sort"] = default_sort
    if params["direction"] not in ("asc", "desc"):
        params["direction"] = default_direction
    if params["per_page"] not in ("10", "25", "50"):
        params["per_page"] = "10"
    product_ids = {p["id"] for p in snapshot["products"]}
    if params["product"] and params["product"] not in product_ids | ({"unassigned"} if kind == "components" else set()):
        return ServiceResult.failure("Product not found", status_code=404)
    rows = snapshot["rows"]
    if search := params["search"].casefold():
        rows = [
            row
            for row in rows
            if search
            in " ".join(
                (
                    row["name"],
                    row.get("description", ""),
                    row.get("product_name", ""),
                    *(p["name"] for p in row.get("products", [])),
                )
            ).casefold()
        ]
    if params["visibility"] != "all":
        rows = [row for row in rows if row["visibility"] == params["visibility"]]
    if params["product"] == "unassigned":
        rows = [row for row in rows if not row["product_ids"]]
    elif params["product"]:
        rows = [row for row in rows if params["product"] in row["product_ids"]]
    # Cheap filters run first, even when risk or security ordering requires
    # evaluating every matching row. Never sort/filter only the current page.
    needs_details = hydrate is not None and (params["risk"] != "all" or any(params["sort"] not in row for row in rows))
    if needs_details and hydrate is not None:
        rows = hydrate([row["id"] for row in rows])
    if params["risk"] == "attention":
        rows = [row for row in rows if row["vulnerabilities"] > 0]
    elif params["risk"] == "clear":
        rows = [row for row in rows if row["assessed"] and not row["vulnerabilities"] and not row["unassessed"]]
    elif params["risk"] == "unassessed":
        rows = [row for row in rows if row["security_applicable"] and (not row["assessed"] or row["unassessed"])]
    sort = params["sort"]
    rows.sort(
        key=lambda row: (row[sort].casefold() if isinstance(row[sort], str) else row[sort], row["id"]),
        reverse=params["direction"] == "desc",
    )
    page = Paginator(rows, int(params["per_page"])).get_page(request.GET.get("page", 1))
    if hydrate is not None and not needs_details:
        details = {row["id"]: row for row in hydrate([row["id"] for row in page.object_list])}
        page.object_list = [details[row["id"]] for row in page.object_list if row["id"] in details]
    headers = [
        {
            "key": key,
            "label": label,
            "href": _url(
                params,
                base_url=base_url,
                sort=key,
                direction="desc" if sort == key and params["direction"] == "asc" else "asc",
            ),
            "order": ("ascending" if params["direction"] == "asc" else "descending") if sort == key else "none",
        }
        for key, label in COLUMNS[kind]
    ]
    inventory = {
        "base_url": base_url,
        "content_id": content_id,
        "scope_product": product_id,
        "kind": kind,
        "singular": {"products": "product", "releases": "release", "components": "component"}[kind],
        "heading": HEADINGS[kind][0],
        "heading_subtitle": HEADINGS[kind][1],
        "document_title": f"{HEADINGS[kind][0]} · sbomify",
        "rows": list(page),
        "params": params,
        "headers": headers,
        "page": page,
        "total": snapshot["counts"][kind],
        "products": snapshot["products"],
        "tabs": [
            {
                "id": key,
                "label": key.title(),
                "is_active": key == kind,
                # The heading the page takes when this tab is the open one, so a
                # tab switch can say where it landed without another round trip.
                "heading": HEADINGS[key][0],
                "subtitle": HEADINGS[key][1],
                "document_title": f"{HEADINGS[key][0]} · sbomify",
                # The badge counts the scope its own link opens. A tab that
                # carries the product filter counts that product; one that drops
                # it counts the workspace, so no badge promises rows the table
                # under it will not show.
                "badge": str(tab_counts[key] if tab_counts and key != "products" else snapshot["counts"][key]),
                "href": _tab_href(params, kind, key),
            }
            for key in KINDS
        ],
        "query": urlencode(params),
        "page_range": list(page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
        "refresh_url": _url(params, base_url=base_url, page=page.number),
        "reset_url": base_url,
    }
    return ServiceResult.success({"inventory": inventory})
