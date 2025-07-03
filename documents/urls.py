from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    # Document detail views
    path("document/<str:document_id>/", views.document_details_private, name="document_details"),
    path("public/document/<str:document_id>/", views.document_details_public, name="document_details_public"),
    path(
        "document/download/<str:document_id>",
        views.document_download,
        name="document_download",
    ),
]
