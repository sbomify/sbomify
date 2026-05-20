"""URL routes for the OIDC trusted-publishers UI.

Mounted under ``/components/<component_id>/trusted-publishers/`` from
the root URLConf so URLs resolve naturally in the component-settings
context.
"""

from __future__ import annotations

from django.urls import path

from sbomify.apps.oidc.views import TrustedPublisherDeleteView, TrustedPublishersView

app_name = "oidc"

urlpatterns = [
    path(
        "components/<str:component_id>/trusted-publishers/",
        TrustedPublishersView.as_view(),
        name="trusted_publishers",
    ),
    path(
        "components/<str:component_id>/trusted-publishers/<str:binding_id>/delete/",
        TrustedPublisherDeleteView.as_view(),
        name="trusted_publisher_delete",
    ),
]
