"""URL configuration for the plugins app."""

from django.urls import path

from .views import TeamPluginSettingsView

app_name = "plugins"

# Django URL patterns
urlpatterns = [
    path(
        "settings/<team_key>",
        TeamPluginSettingsView.as_view(),
        name="team_plugin_settings",
    ),
]

# Note: API endpoints are registered in sbomify/apis.py using the Ninja router
# from sbomify.apps.plugins.apis import router as plugins_router
