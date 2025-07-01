from django.urls import path
from django.urls.resolvers import URLPattern
from django.views.generic import RedirectView

from . import views

app_name = "sboms"
urlpatterns: list[URLPattern] = [
    # Backward compatibility redirects for URLs that now have trailing slashes
    path("products", RedirectView.as_view(pattern_name="sboms:products_dashboard", permanent=True)),
    path("projects", RedirectView.as_view(pattern_name="sboms:projects_dashboard", permanent=True)),
    path("components", RedirectView.as_view(pattern_name="sboms:components_dashboard", permanent=True)),
    path("product/<str:product_id>", RedirectView.as_view(pattern_name="sboms:product_details", permanent=True)),
    path("project/<str:project_id>", RedirectView.as_view(pattern_name="sboms:project_details", permanent=True)),
    path("component/<str:component_id>", RedirectView.as_view(pattern_name="sboms:component_details", permanent=True)),
    path(
        "public/product/<str:product_id>",
        RedirectView.as_view(pattern_name="sboms:product_details_public", permanent=True),
    ),
    path(
        "public/project/<str:project_id>",
        RedirectView.as_view(pattern_name="sboms:project_details_public", permanent=True),
    ),
    path(
        "public/component/<str:component_id>",
        RedirectView.as_view(pattern_name="sboms:component_details_public", permanent=True),
    ),
    path("sbom/<str:sbom_id>", RedirectView.as_view(pattern_name="sboms:sbom_details", permanent=True)),
    path("public/sbom/<str:sbom_id>", RedirectView.as_view(pattern_name="sboms:sbom_details_public", permanent=True)),
    path("products/", views.products_dashboard, name="products_dashboard"),
    path(
        "product/<str:product_id>/",
        views.product_details_private,
        name="product_details",
    ),
    path(
        "public/product/<str:product_id>/",
        views.product_details_public,
        name="product_details_public",
    ),
    path("projects/", views.projects_dashboard, name="projects_dashboard"),
    path(
        "project/<str:project_id>/",
        views.project_details_private,
        name="project_details",
    ),
    path(
        "public/project/<str:project_id>/",
        views.project_details_public,
        name="project_details_public",
    ),
    path("components/", views.components_dashboard, name="components_dashboard"),
    path(
        "component/<str:component_id>/",
        views.component_details_private,
        name="component_details",
    ),
    path(
        "public/component/<str:component_id>/",
        views.component_details_public,
        name="component_details_public",
    ),
    path(
        "component/<str:component_id>/transfer",
        views.transfer_component_to_team,
        name="transfer_component",
    ),
    path(
        "sbom/download/<str:sbom_id>",
        views.sbom_download,
        name="sbom_download",
    ),
    path(
        "project/<str:project_id>/sbom/download",
        views.sbom_download_project,
        name="sbom_download_project",
    ),
    path(
        "product/<str:product_id>/sbom/download",
        views.sbom_download_product,
        name="sbom_download_product",
    ),
    path("sbom/<str:sbom_id>/", views.sbom_details_private, name="sbom_details"),
    path("public/sbom/<str:sbom_id>/", views.sbom_details_public, name="sbom_details_public"),
    path(
        "sbom/<str:sbom_id>/vulnerabilities",
        views.sbom_vulnerabilities,
        name="sbom_vulnerabilities",
    ),
]
