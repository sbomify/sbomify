from django.urls import path

from sbomify.apps.documents.views import DocumentDownloadView, DocumentsTableView

app_name = "documents"

urlpatterns = [
    path(
        "document/download/<str:document_id>",
        DocumentDownloadView.as_view(),
        name="document_download",
    ),
    path(
        "component/<str:component_id>/documents/",
        DocumentsTableView.as_view(),
        name="documents_table",
        kwargs={"is_public_view": False},
    ),
    path(
        "public/component/<str:component_id>/documents/",
        DocumentsTableView.as_view(),
        name="documents_table_public",
        kwargs={"is_public_view": True},
    ),
]
