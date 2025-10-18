from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard", views.dashboard, name="dashboard"),
    path("settings", views.user_settings, name="settings"),
    path("access_tokens/<token_id>/delete", views.delete_access_token, name="delete_access_token"),
    path("logout", views.logout, name="logout"),
    path("login_error", views.login_error, name="login_error"),
    # Webhook support for Keycloak can be added here in the future if needed.
    # https://github.com/sbomify/sbomify/issues/69
    path("login", views.keycloak_login, name="keycloak_login"),
    # Product/Project/Component URLs - moved from sboms app
    # Backward compatibility redirects for URLs that now have trailing slashes
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
    # Main URLs
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
    path("components/", views.ComponentsDashboardView.as_view(), name="components_dashboard"),
    path(
        "component/<str:component_id>/",
        views.ComponentDetailsPrivateView.as_view(),
        name="component_details",
    ),
    path("releases/", views.releases_dashboard, name="releases_dashboard"),
    path(
        "component/<str:component_id>/detailed/",
        views.ComponentDetailedPrivateView.as_view(),
        name="component_detailed",
    ),
    path(
        "public/component/<str:component_id>/",
        views.ComponentDetailsPublicView.as_view(),
        name="component_details_public",
    ),
    path(
        "public/component/<str:component_id>/detailed/",
        views.ComponentDetailedPublicView.as_view(),
        name="component_detailed_public",
    ),
    path(
        "component/<str:component_id>/transfer",
        views.transfer_component_to_team,
        name="transfer_component",
    ),
    # Release URLs
    path(
        "product/<str:product_id>/releases/",
        views.product_releases_private,
        name="product_releases",
    ),
    path(
        "public/product/<str:product_id>/releases/",
        views.product_releases_public,
        name="product_releases_public",
    ),
    path(
        "product/<str:product_id>/release/<str:release_id>/",
        views.release_details_private,
        name="release_details",
    ),
    path(
        "public/product/<str:product_id>/release/<str:release_id>/",
        views.release_details_public,
        name="release_details_public",
    ),
    # Download URLs
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
    path(
        "component/<str:component_id>/metadata",
        views.get_component_metadata,
        name="get_component_metadata",
    ),
    # Support contact pages
    path("support/contact/", views.support_contact, name="support_contact"),
    path("support/contact/success/", views.support_contact_success, name="support_contact_success"),
]
