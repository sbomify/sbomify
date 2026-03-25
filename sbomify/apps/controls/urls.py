"""URL configuration for the controls app."""

from django.urls import path

from .views import ControlsCatalogView, ControlsStatusView, ProductControlsStatusView

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
    path(
        "<team_key>/product/<product_id>/status",
        ProductControlsStatusView.as_view(),
        name="product_status_update",
    ),
]
