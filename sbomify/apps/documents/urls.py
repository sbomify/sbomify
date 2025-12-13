from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    # Document detail views
    # On custom domains, the private view delegates to public view for slug-based lookups
    path("document/<str:document_id>/", views.document_details_private, name="document_details"),
    path("public/document/<str:document_id>/", views.document_details_public, name="document_details_public"),
    path(
        "document/download/<str:document_id>",
        views.document_download,
        name="document_download",
    ),
    path(
        "component/<str:component_id>/documents/",
        views.DocumentsTableView.as_view(),
        name="documents_table",
        kwargs={"is_public_view": False},
    ),
    path(
        "public/component/<str:component_id>/documents/",
        views.DocumentsTableView.as_view(),
        name="documents_table_public",
        kwargs={"is_public_view": True},
    ),
]
