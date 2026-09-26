"""URL configuration for the plugins app."""

from django.urls import path

from .views import (
    AssessmentResultsCardView,
    AssessmentRunFindingsView,
    PluginsPageView,
    PluginsSummaryView,
    TeamPluginSettingsView,
)

app_name = "plugins"

# Django URL patterns
urlpatterns = [
    path(
        "",
        PluginsPageView.as_view(),
        name="plugins_page",
    ),
    path(
        "summary/",
        PluginsSummaryView.as_view(),
        name="plugins_summary",
    ),
    path(
        "settings/<team_key>",
        TeamPluginSettingsView.as_view(),
        name="team_plugin_settings",
    ),
    path(
        "assessments/runs/<str:run_id>/findings/",
        AssessmentRunFindingsView.as_view(),
        name="assessment_run_findings",
    ),
    path(
        "assessments/sboms/<str:sbom_id>/card/",
        AssessmentResultsCardView.as_view(),
        name="assessment_results_card",
    ),
]

# Note: API endpoints are registered in sbomify/apis.py using the Ninja router
# from sbomify.apps.plugins.apis import router as plugins_router
