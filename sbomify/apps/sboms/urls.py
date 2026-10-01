from django.urls import path
from django.urls.resolvers import URLPattern

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
