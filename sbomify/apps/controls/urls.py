"""URL configuration for the controls app."""

from django.urls import path

from .views import ControlsCatalogView, ControlsStatusView

app_name = "controls"

urlpatterns = [
    path(
        "<team_key>/catalog",
        ControlsCatalogView.as_view(),
        name="catalog_action",
    ),
    path(
        "<team_key>/status",
        ControlsStatusView.as_view(),
        name="status_update",
    ),
]
