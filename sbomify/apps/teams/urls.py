from django.urls import path
from django.urls.resolvers import URLPattern

from . import views

app_name = "teams"
urlpatterns: list[URLPattern] = [
    path("", views.TeamsDashboardView.as_view(), name="teams_dashboard"),
    path("switch/<team_key>/", views.switch_team, name="switch_team"),
    path("invite/<team_key>/", views.invite, name="invite_user"),
    path("accept_invite/<invite_id>/", views.accept_invite, name="accept_invite"),
    path("<membership_id>/leave", views.delete_member, name="team_membership_delete"),
    path("<invitation_id>/uninvite", views.delete_invite, name="team_invitation_delete"),
    path("onboarding/", views.onboarding_wizard, name="onboarding_wizard"),
    # Backward compatibility redirects - must come before general patterns
    path("settings/", views.settings_redirect, name="settings_redirect"),
    path("<team_key>/settings/", views.team_settings_redirect, name="team_settings_redirect"),
    # Keep team_details as an alias that redirects to team_settings for backward compatibility
    path("<team_key>/details", views.team_details, name="team_details"),
    # Main team settings (unified interface) - must come after specific patterns
    path("<team_key>", views.TeamSettingsView.as_view(), name="team_settings"),
]
