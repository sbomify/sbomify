from django.urls import path
from django.urls.resolvers import URLPattern
from django.views.generic import RedirectView

from sbomify.apps.sboms.views import (
    ComponentArtifactsView,
    ComponentCryptoPostureView,
    ComponentVexDocumentsView,
    SbomCryptoInventoryView,
    SbomDownloadView,
    SbomsTableView,
    SbomVulnerabilitiesView,
    WorkspaceCryptoView,
)

app_name = "sboms"
urlpatterns: list[URLPattern] = [
    # Product/Component URLs moved to core app - redirect to core
    path("products", RedirectView.as_view(pattern_name="core:products_dashboard", permanent=True)),
    path("components", RedirectView.as_view(pattern_name="core:components_dashboard", permanent=True)),
    path("product/<str:product_id>", RedirectView.as_view(pattern_name="core:product_details", permanent=True)),
    path("component/<str:component_id>", RedirectView.as_view(pattern_name="core:component_details", permanent=True)),
    path(
        "public/product/<str:product_id>",
        RedirectView.as_view(pattern_name="core:product_details_public", permanent=True),
    ),
    path(
        "public/component/<str:component_id>",
        RedirectView.as_view(pattern_name="core:component_details_public", permanent=True),
    ),
    path("products/", RedirectView.as_view(pattern_name="core:products_dashboard", permanent=True)),
    path("components/", RedirectView.as_view(pattern_name="core:components_dashboard", permanent=True)),
    path(
        "product/<str:product_id>/",
        RedirectView.as_view(pattern_name="core:product_details", permanent=True),
    ),
    path(
        "public/product/<str:product_id>/",
        RedirectView.as_view(pattern_name="core:product_details_public", permanent=True),
    ),
    path(
        "component/<str:component_id>/",
        RedirectView.as_view(pattern_name="core:component_details", permanent=True),
    ),
    path(
        "public/component/<str:component_id>/",
        RedirectView.as_view(pattern_name="core:component_details_public", permanent=True),
    ),
    path(
        "component/<str:component_id>/transfer",
        RedirectView.as_view(pattern_name="core:transfer_component", permanent=True),
    ),
    path(
        "product/<str:product_id>/sbom/download",
        RedirectView.as_view(pattern_name="core:sbom_download_product", permanent=True),
    ),
    path(
        "sbom/download/<str:sbom_id>",
        SbomDownloadView.as_view(),
        name="sbom_download",
    ),
    path(
        "sbom/<str:sbom_id>/vulnerabilities",
        SbomVulnerabilitiesView.as_view(),
        name="sbom_vulnerabilities",
    ),
    path(
        "component/<str:component_id>/sboms/",
        SbomsTableView.as_view(),
        name="sboms_table",
        kwargs={"is_public_view": False},
    ),
    path(
        "component/<str:component_id>/artifacts/",
        ComponentArtifactsView.as_view(),
        name="component_artifacts",
    ),
    path(
        "public/component/<str:component_id>/sboms/",
        SbomsTableView.as_view(),
        name="sboms_table_public",
        kwargs={"is_public_view": True},
    ),
    path(
        "component/<str:component_id>/vex/",
        ComponentVexDocumentsView.as_view(),
        name="component_vex_documents",
    ),
    path(
        "sbom/<str:sbom_id>/crypto-inventory",
        SbomCryptoInventoryView.as_view(),
        name="sbom_crypto_inventory",
    ),
    path(
        "workspaces/<str:team_key>/crypto/",
        WorkspaceCryptoView.as_view(),
        name="workspace_crypto",
    ),
    path(
        "component/<str:component_id>/crypto-posture",
        ComponentCryptoPostureView.as_view(),
        name="component_crypto_posture",
    ),
]
