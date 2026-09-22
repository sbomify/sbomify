"""Product details compose the same inventory and security data as the workspace."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.urls import reverse
from pydantic import ValidationError

from sbomify.apps.compliance.models import CRAAssessment
from sbomify.apps.compliance.permissions import check_cra_access
from sbomify.apps.core.apis import get_product, patch_product
from sbomify.apps.core.authz import can
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.schemas import ProductPatchSchema
from sbomify.apps.core.services.inventory_page import COLUMNS, build_inventory_snapshot, build_inventory_table
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.tea.mappers import get_product_tei_urn


def build_product_page_context(request: HttpRequest, product_id: str) -> ServiceResult[dict[str, Any]]:
    """Keep the route's workspace boundary independent of table query parameters."""
    workspace_key = (request.session.get("current_team") or {}).get("key")
    instance = Product.objects.select_related("team").filter(id=product_id, team__key=workspace_key).first()
    if instance is None or not can(request, "product:read", instance):
        return ServiceResult.failure("Product not found", status_code=404)
    status, product = get_product(request, product_id)
    if status != 200:
        return ServiceResult.failure(product.get("detail", "Product not found"), status_code=status)

    product.pop("components", None)
    workspace = instance.team
    components = build_inventory_snapshot(workspace, "components", product_id=product_id)
    table = build_inventory_table(
        request,
        components,
        kind="components",
        product_id=product_id,
        base_url=reverse("core:product_details", args=[product_id]),
        content_id="product-components",
    )
    if not table.ok:
        return table
    if request.headers.get("HX-Target") == "product-components":
        return ServiceResult.success({**(table.value or {}), "product": product})
    releases = build_inventory_snapshot(workspace, "releases", product_id=product_id)
    release_rows = sorted(
        releases["rows"],
        key=lambda row: (
            row["release_type"] != "Rolling latest",
            -(row["released_at"] or row["created_at"]).timestamp(),
        ),
    )
    rows = components["rows"]
    security_rows = [row for row in rows if row["security_applicable"]]
    metrics = {
        "components": len(rows),
        "artifacts": sum(row["artifact_count"] for row in rows),
        "open": sum(row["vulnerabilities"] for row in security_rows),
        "past_sla": sum(row["past_sla"] for row in security_rows),
        "unassessed": sum(row["unassessed"] for row in security_rows),
    }
    product_tei = get_product_tei_urn(product_id, workspace.id)
    copy_values = [{"value": product_id, "title": f"Product ID: {product_id} (click to copy)"}]
    if product_tei:
        copy_values.append({"value": product_tei, "title": f"TEI: {product_tei} (click to copy)"})
    has_cra_access = can(request, "workspace:administer", workspace) and check_cra_access(
        billing_plan_key=workspace.billing_plan
    )
    cra = CRAAssessment.objects.filter(product=instance, team=workspace).first() if has_cra_access else None
    return ServiceResult.success(
        {
            **(table.value or {}),
            "product": product,
            "metrics": metrics,
            "has_sboms": any(row["has_sbom"] for row in rows),
            "release_editor_data": release_rows,
            "release_inventory": {
                "kind": "releases",
                "singular": "release",
                "scope_product": product_id,
                "rows": release_rows[:5],
                "total": len(release_rows),
                "headers": [{"label": label} for _, label in COLUMNS["releases"]],
            },
            "available_components": list(
                Component.objects.filter(team=workspace, is_global=False)
                .exclude(products=instance)
                .order_by("name", "id")
                .values("id", "name")
            )
            if can(request, "product:manage", instance)
            else [],
            "APP_BASE_URL": settings.APP_BASE_URL,
            "current_team": request.session.get("current_team", {}),
            "header_copy_values": copy_values,
            "product_tei": product_tei,
            "has_cra_access": has_cra_access,
            "cra_assessment": cra,
            "team_billing_plan": workspace.billing_plan,
        }
    )


def update_product_page(request: HttpRequest, product_id: str) -> ServiceResult[str]:
    """Apply one relationship change to the current membership, never a browser's stale list."""
    workspace_key = (request.session.get("current_team") or {}).get("key")
    with transaction.atomic():
        product = Product.objects.select_for_update().filter(id=product_id, team__key=workspace_key).first()
        if product is None:
            return ServiceResult.failure("Product not found", status_code=404)
        if not can(request, "product:manage", product):
            return ServiceResult.failure("You do not have permission to update this product", status_code=403)
        action = request.POST.get("action", "")
        if action == "update_description":
            data: dict[str, Any] = {"description": request.POST.get("description", "").strip()}
            message = "Description updated"
        elif action in ("assign_component", "remove_component"):
            component_id = request.POST.get("component_id", "")
            component = Component.objects.filter(id=component_id, team_id=product.team_id, is_global=False).first()
            if component is None:
                return ServiceResult.failure("Component not found", status_code=404)
            ids = set(product.components.values_list("id", flat=True))
            if action == "assign_component":
                ids.add(component_id)
                message = "Component assigned"
            else:
                ids.discard(component_id)
                message = "Component removed from product"
            data = {"component_ids": sorted(ids)}
        else:
            return ServiceResult.failure("Choose a product action", status_code=400)
        try:
            payload = ProductPatchSchema.model_validate(data)
        except ValidationError:
            return ServiceResult.failure("Check the product details and try again", status_code=400)
        status, result = patch_product(request, product_id, payload)
        if status != 200:
            return ServiceResult.failure(result.get("detail", "Unable to update product"), status_code=status)
    return ServiceResult.success(message)


def build_product_releases_context(request: HttpRequest, product_id: str) -> ServiceResult[dict[str, Any]]:
    """The product's full release history uses the workspace inventory's table."""
    workspace_key = (request.session.get("current_team") or {}).get("key")
    instance = Product.objects.select_related("team").filter(id=product_id, team__key=workspace_key).first()
    if instance is None or not can(request, "product:read", instance):
        return ServiceResult.failure("Product not found", status_code=404)
    status, product = get_product(request, product_id)
    if status != 200:
        return ServiceResult.failure(product.get("detail", "Product not found"), status_code=status)
    product.pop("components", None)
    snapshot = build_inventory_snapshot(instance.team, "releases", product_id=product_id)
    result = build_inventory_table(
        request,
        snapshot,
        kind="releases",
        product_id=product_id,
        base_url=reverse("core:product_releases", args=[product_id]),
        content_id="product-releases-content",
    )
    if not result.ok:
        return result
    return ServiceResult.success(
        {
            **(result.value or {}),
            "product": product,
            "release_editor_data": snapshot["rows"],
            "breadcrumb_items": [
                {"label": product["name"], "url": reverse("core:product_details", args=[product_id])},
                {"label": "Releases"},
            ],
        }
    )
