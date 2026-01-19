from django.urls import path

from sbomify.apps.documents.views import DocumentDownloadView, DocumentsTableView
from sbomify.apps.documents.views.access_requests import AccessRequestQueueView, AccessRequestView, NDASigningView

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
    path(
        "workspace/<str:team_key>/access-request",
        AccessRequestView.as_view(),
        name="request_access",
    ),
    path(
        "workspace/<str:team_key>/access-request/<str:request_id>/sign-nda",
        NDASigningView.as_view(),
        name="sign_nda",
    ),
    path(
        "workspace/<str:team_key>/access-requests",
        AccessRequestQueueView.as_view(),
        name="access_request_queue",
    ),
]
