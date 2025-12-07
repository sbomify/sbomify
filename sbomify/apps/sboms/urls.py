from django.urls import path
from django.urls.resolvers import URLPattern
from django.views.generic import RedirectView

from . import views
from sbomify.apps.sboms.views.sboms_table import SbomsTableView

app_name = "sboms"
urlpatterns: list[URLPattern] = [
    # Product/Project/Component URLs moved to core app - redirect to core
    path("products", RedirectView.as_view(pattern_name="core:products_dashboard", permanent=True)),
    path("projects", RedirectView.as_view(pattern_name="core:projects_dashboard", permanent=True)),
    path("components", RedirectView.as_view(pattern_name="core:components_dashboard", permanent=True)),
    path("product/<str:product_id>", RedirectView.as_view(pattern_name="core:product_details", permanent=True)),
    path("project/<str:project_id>", RedirectView.as_view(pattern_name="core:project_details", permanent=True)),
    path("component/<str:component_id>", RedirectView.as_view(pattern_name="core:component_details", permanent=True)),
    path(
        "public/product/<str:product_id>",
        RedirectView.as_view(pattern_name="core:product_details_public", permanent=True),
    ),
    path(
        "public/project/<str:project_id>",
        RedirectView.as_view(pattern_name="core:project_details_public", permanent=True),
    ),
    path(
        "public/component/<str:component_id>",
        RedirectView.as_view(pattern_name="core:component_details_public", permanent=True),
    ),
    path("products/", RedirectView.as_view(pattern_name="core:products_dashboard", permanent=True)),
    path("projects/", RedirectView.as_view(pattern_name="core:projects_dashboard", permanent=True)),
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
        "project/<str:project_id>/",
        RedirectView.as_view(pattern_name="core:project_details", permanent=True),
    ),
    path(
        "public/project/<str:project_id>/",
        RedirectView.as_view(pattern_name="core:project_details_public", permanent=True),
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
        "project/<str:project_id>/sbom/download",
        RedirectView.as_view(pattern_name="core:sbom_download_project", permanent=True),
    ),
    path(
        "product/<str:product_id>/sbom/download",
        RedirectView.as_view(pattern_name="core:sbom_download_product", permanent=True),
    ),
    # SBOM-specific URLs - redirect old URLs to new component detailed structure
    path("sbom/<str:sbom_id>", views.redirect_sbom_to_component_detailed, name="sbom_details_redirect"),  # legacy
    path(
        "public/sbom/<str:sbom_id>",
        views.redirect_sbom_to_component_detailed_public,
        name="sbom_details_public_redirect",
    ),  # legacy
    path(
        "sbom/download/<str:sbom_id>",
        views.sbom_download,
        name="sbom_download",
    ),
    path("sbom/<str:sbom_id>/", views.redirect_sbom_to_component_detailed, name="sbom_details"),  # legacy
    path(
        "public/sbom/<str:sbom_id>/", views.redirect_sbom_to_component_detailed_public, name="sbom_details_public"
    ),  # legacy
    path(
        "sbom/<str:sbom_id>/vulnerabilities",
        views.sbom_vulnerabilities,
        name="sbom_vulnerabilities",
    ),
    path(
        "component/<str:component_id>/sboms/",
        SbomsTableView.as_view(),
        name="sboms_table",
        kwargs={"is_public_view": False},
    ),
    path(
        "public/component/<str:component_id>/sboms/",
        SbomsTableView.as_view(),
        name="sboms_table_public",
        kwargs={"is_public_view": True},
    ),
]
