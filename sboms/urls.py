from django.urls import path
from django.urls.resolvers import URLPattern

from . import views

app_name = "sboms"
urlpatterns: list[URLPattern] = [
    path("products", views.products_dashboard, name="products_dashboard"),
    path(
        "product/<str:product_id>",
        views.product_details_private,
        name="product_details",
    ),
    path(
        "public/product/<str:product_id>",
        views.product_details_public,
        name="product_details_public",
    ),
    path(
        "product/<str:product_id>/delete",
        views.delete_product,
        name="delete_product",
    ),
    path("projects", views.projects_dashboard, name="projects_dashboard"),
    path(
        "project/<str:project_id>",
        views.project_details_private,
        name="project_details",
    ),
    path(
        "public/project/<str:project_id>",
        views.project_details_public,
        name="project_details_public",
    ),
    path(
        "project/<str:project_id>/delete",
        views.delete_project,
        name="delete_project",
    ),
    path("components", views.components_dashboard, name="components_dashboard"),
    path(
        "component/<str:component_id>",
        views.component_details_private,
        name="component_details",
    ),
    path(
        "public/component/<str:component_id>",
        views.component_details_public,
        name="component_details_public",
    ),
    path(
        "component/<str:component_id>/delete",
        views.delete_component,
        name="delete_component",
    ),
    path(
        "transfer-component/<str:component_id>",
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
    path("sbom/<str:sbom_id>", views.sbom_details_private, name="sbom_details"),
    path("public/sbom/<str:sbom_id>", views.sbom_details_public, name="sbom_details_public"),
    path(
        "sbom/<str:sbom_id>/vulnerabilities",
        views.sbom_vulnerabilities,
        name="sbom_vulnerabilities",
    ),
]
