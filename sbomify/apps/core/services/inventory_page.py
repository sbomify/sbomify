"""Workspace inventory for the Products area, including its release and component views."""

from __future__ import annotations

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
from sbomify.apps.teams.models import Team
from sbomify.apps.vulnerability_scanning.posture import build_release_vuln_postures

KINDS = ("products", "releases", "components")
SEVERITIES = ("total", "critical", "high", "medium", "low")
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


def _url(params: dict[str, Any], *, base_url: str = "", **changes: Any) -> str:
    return (base_url or reverse("core:products_dashboard")) + "?" + urlencode({**params, **changes})


def build_inventory_snapshot(workspace: Team, kind: str, *, product_id: str = "") -> dict[str, Any]:
    """Batch joins and scans for an authorised workspace or product."""
    component_scope = Q(products__id=product_id) if product_id else Q()
    product_scope = Q(id=product_id) if product_id else Q()
    release_scope = Q(product_id=product_id) if product_id else Q()
    components = list(
        Component.objects.filter(component_scope, team=workspace)
        .annotate(sbom_count=Count("sbom", distinct=True), document_count=Count("document", distinct=True))
        .order_by("name", "id")
    )
    products = list(
        Product.objects.filter(product_scope, team=workspace)
        .annotate(release_count=Count("releases", distinct=True))
        .prefetch_related(Prefetch("components", queryset=Component.objects.filter(team=workspace).only("id")))
        .order_by("name", "id")
    )
    releases = list(
        Release.objects.filter(release_scope, product__team=workspace)
        .select_related("product")
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
    tabs_count = {"products": len(products), "components": len(components), "releases": len(releases)}
    choices = [{"id": product.id, "name": product.name} for product in products]
    memberships: dict[str, list[dict[str, str]]] = {}
    for product in products:
        for component in product.components.all():
            memberships.setdefault(component.id, []).append({"id": product.id, "name": product.name})

    rows: list[dict[str, Any]] = []
    if kind == "releases":
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
                    "release_count": product.release_count,
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
    snapshot = build_inventory_snapshot(workspace, kind)
    return build_inventory_table(request, snapshot, kind=kind)


def build_inventory_table(
    request: HttpRequest,
    snapshot: dict[str, Any],
    *,
    kind: str,
    base_url: str = "",
    content_id: str = "inventory-content",
    product_id: str = "",
) -> ServiceResult[dict[str, Any]]:
    """One server filter, sort and pagination contract for lists and detail pages.

    The caller authorises and scopes the snapshot before passing it here. A
    product scope is fixed by the route and cannot be widened by a query string.
    """
    base_url = base_url or reverse("core:products_dashboard")
    params: dict[str, Any] = {
        "view": kind,
        "search": request.GET.get("search", "").strip(),
        "risk": request.GET.get("risk", "all"),
        "visibility": request.GET.get("visibility", "all"),
        "product": product_id or (request.GET.get("product", "") if kind != "products" else ""),
        "sort": request.GET.get("sort", "name"),
        "direction": request.GET.get("direction", "asc"),
        "per_page": request.GET.get("per_page", "10"),
    }
    if params["risk"] not in ("all", "attention", "clear", "unassessed"):
        params["risk"] = "all"
    visibility_options = ("all", "public", "private", "gated") if kind == "components" else ("all", "public", "private")
    if params["visibility"] not in visibility_options:
        params["visibility"] = "all"
    if params["sort"] not in dict(COLUMNS[kind]):
        params["sort"] = "name"
    if params["direction"] not in ("asc", "desc"):
        params["direction"] = "asc"
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
    if params["risk"] == "attention":
        rows = [row for row in rows if row["vulnerabilities"] > 0]
    elif params["risk"] == "clear":
        rows = [row for row in rows if row["assessed"] and not row["vulnerabilities"] and not row["unassessed"]]
    elif params["risk"] == "unassessed":
        rows = [row for row in rows if row["security_applicable"] and (not row["assessed"] or row["unassessed"])]
    if params["visibility"] != "all":
        rows = [row for row in rows if row["visibility"] == params["visibility"]]
    if params["product"] == "unassigned":
        rows = [row for row in rows if not row["product_ids"]]
    elif params["product"]:
        rows = [row for row in rows if params["product"] in row["product_ids"]]
    sort = params["sort"]
    rows.sort(
        key=lambda row: (row[sort].casefold() if isinstance(row[sort], str) else row[sort], row["id"]),
        reverse=params["direction"] == "desc",
    )
    page = Paginator(rows, int(params["per_page"])).get_page(request.GET.get("page", 1))
    headers = [
        {
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
                "badge": str(snapshot["counts"][key]),
                "href": _url(
                    {
                        "view": key,
                        "product": params["product"] if key != "products" and params["product"] != "unassigned" else "",
                    }
                ),
            }
            for key in KINDS
        ],
        "query": urlencode(params),
        "page_range": list(page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
        "refresh_url": _url(params, base_url=base_url, page=page.number),
        "reset_url": _url({"view": kind}, base_url=base_url),
    }
    return ServiceResult.success({"inventory": inventory})
