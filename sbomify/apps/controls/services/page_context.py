"""Shared context for workspace controls and product overrides."""

from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from sbomify.apps.controls.models import ControlCatalog, ControlStatus
from sbomify.apps.controls.services.status_service import get_controls_detail
from sbomify.apps.core.authz import can
from sbomify.apps.core.models import Product
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import Team

# The built-in control catalogues offered as tiles on the Controls tab.
# ``catalog_service`` discovers the catalogues themselves by globbing
# ``controls/data``, so this list is the one place that has to be kept in
# step by hand; ``test_every_builtin_catalogue_has_a_tile_in_settings``
# fails if it drifts. Entries are (slug, catalogue name, tile label, icon).
BUILTIN_CATALOG_TILES: list[tuple[str, str, str, str]] = [
    ("soc2-type2", "SOC 2 Type II", "SOC 2 Type II", "fa-shield-halved"),
    ("iso27001-2022", "ISO 27001:2022", "ISO 27001", "fa-certificate"),
    ("nist-csf-2", "NIST Cybersecurity Framework 2.0", "NIST CSF 2.0", "fa-landmark"),
    ("cis-controls-v8", "CIS Controls v8", "CIS v8", "fa-lock"),
    ("hipaa", "HIPAA", "HIPAA", "fa-heart-pulse"),
    ("gdpr", "GDPR", "GDPR", "fa-user-shield"),
    ("cmmc-2", "CMMC 2.0", "CMMC 2.0", "fa-jet-fighter"),
    ("csa-ccm-v4", "CSA CCM", "CSA CCM", "fa-cloud"),
    ("pci-dss-v4", "PCI DSS", "PCI DSS", "fa-credit-card"),
    ("nist-800-53-r5", "NIST SP 800-53", "NIST 800-53", "fa-building-columns"),
    ("nist-800-171-r2", "NIST SP 800-171", "NIST 800-171", "fa-building-lock"),
]


def controls_table_context(
    request: HttpRequest, catalog: ControlCatalog, product: Product | None = None
) -> dict[str, Any]:
    detail = get_controls_detail(catalog, product=product)
    categories = detail.value or []
    status_url = (
        reverse("controls:product_status_update", args=[catalog.team.key, product.pk])
        if product
        else reverse("controls:status_update", args=[catalog.team.key])
    )
    return {
        "catalog": catalog,
        "categories": categories,
        "total": sum(len(category["controls"]) for category in categories),
        "product": product,
        "can_edit": can(request, "workspace:administer", catalog.team),
        "status_url": status_url,
        "bulk_url": reverse("controls:bulk_category_update", args=[catalog.team.key]),
        "statuses": ControlStatus.Status.choices,
    }


def build_controls_settings(request: HttpRequest, workspace_key: str) -> ServiceResult[dict[str, Any]]:
    workspace = Team.objects.filter(key=workspace_key).first()
    if workspace is None or not can(request, "workspace:administer", workspace):
        return ServiceResult.failure("You cannot manage this workspace's controls", status_code=403)

    catalogs = list(ControlCatalog.objects.filter(team=workspace).select_related("team"))
    builtins = {
        catalog.name: catalog for catalog in reversed(catalogs) if catalog.source == ControlCatalog.Source.BUILTIN
    }
    frameworks: list[dict[str, Any]] = [
        {"key": key, "name": name, "catalog": builtins.get(name)} for key, name, _label, _icon in BUILTIN_CATALOG_TILES
    ]
    represented_ids = {row["catalog"].pk for row in frameworks if row["catalog"]}
    frameworks.extend(
        {"key": "__custom__", "name": catalog.name, "catalog": catalog}
        for catalog in catalogs
        if catalog.pk not in represented_ids
    )
    return ServiceResult.success(
        {
            "frameworks": frameworks,
            "active_controls_tables": [
                controls_table_context(request, catalog) for catalog in catalogs if catalog.is_active
            ],
        }
    )


def build_product_controls(request: HttpRequest, workspace_key: str, product_id: str) -> ServiceResult[dict[str, Any]]:
    current_key = (request.session.get("current_team") or {}).get("key")
    product = Product.objects.select_related("team").filter(pk=product_id, team__key=workspace_key).first()
    if current_key != workspace_key or product is None or not can(request, "product:read", product):
        return ServiceResult.failure("Product not found", status_code=404)
    catalogs = ControlCatalog.objects.filter(team=product.team, is_active=True).select_related("team")
    return ServiceResult.success(
        {
            "active_controls_tables": [controls_table_context(request, catalog, product) for catalog in catalogs],
            "controls_settings_url": reverse("teams:team_settings_tab", args=[workspace_key, "controls"]),
            "can_manage_controls": can(request, "workspace:administer", product.team),
        }
    )
