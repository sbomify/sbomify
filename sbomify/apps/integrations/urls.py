"""URL configuration for the integrations app.

The callback has no ``team_key`` on purpose: providers register one exact
redirect URI, so the workspace travels in the session instead. See
``oauth.py``.
"""

from django.urls import path

from .views import IntegrationCallbackView, IntegrationConnectView, IntegrationsView

app_name = "integrations"

urlpatterns = [
    path("<team_key>/", IntegrationsView.as_view(), name="panel"),
    path("<team_key>/connect/<provider>", IntegrationConnectView.as_view(), name="connect"),
    path("oauth/<provider>/callback", IntegrationCallbackView.as_view(), name="callback"),
]
