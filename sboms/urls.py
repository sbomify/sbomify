from django.urls import path
from django.urls.resolvers import URLPattern
from django.views.generic import RedirectView

from . import views

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
    # SBOM-specific URLs - use dedicated SBOM details views
    path("sbom/<str:sbom_id>", views.sbom_details_private, name="sbom_details_redirect"),
    path(
        "public/sbom/<str:sbom_id>",
        views.sbom_details_public,
        name="sbom_details_public_redirect",
    ),
    path(
        "sbom/download/<str:sbom_id>",
        views.sbom_download,
        name="sbom_download",
    ),
    path("sbom/<str:sbom_id>/", views.sbom_details_private, name="sbom_details"),
    path("public/sbom/<str:sbom_id>/", views.sbom_details_public, name="sbom_details_public"),
    path(
        "sbom/<str:sbom_id>/vulnerabilities/",
        views.sbom_vulnerabilities,
        name="sbom_vulnerabilities",
    ),
]
