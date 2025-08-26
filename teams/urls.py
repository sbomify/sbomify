from django.urls import path
from django.urls.resolvers import URLPattern

from . import views

app_name = "teams"
urlpatterns: list[URLPattern] = [
    path("", views.teams_dashboard, name="teams_dashboard"),
    path("switch/<team_key>/", views.switch_team, name="switch_team"),
    path("set_default/<membership_id>/", views.set_default_team, name="set_default_team"),
    path("delete/<team_key>/", views.delete_team, name="delete_team"),
    path("invite/<team_key>/", views.invite, name="invite_user"),
    path("accept_invite/<invite_id>/", views.accept_invite, name="accept_invite"),
    path("<membership_id>/leave", views.delete_member, name="team_membership_delete"),
    path("<invitation_id>/uninvite", views.delete_invite, name="team_invitation_delete"),
    path("<team_key>/member/<int:member_id>/update-role/", views.update_member_role, name="update_member_role"),
    path("<team_key>/member/<int:member_id>/remove/", views.remove_member, name="remove_member"),
    path("<team_key>/invitation/<int:invitation_id>/delete/", views.delete_invitation, name="delete_invitation"),
    path("<team_key>/branding/update/", views.update_branding, name="update_branding"),
    path(
        "<team_key>/vulnerability-settings/update/",
        views.update_vulnerability_settings,
        name="update_vulnerability_settings",
    ),
    path("<team_key>/dt-servers/add/", views.add_dt_server, name="add_dt_server"),
    path("<team_key>/dt-servers/<str:server_id>/delete/", views.delete_dt_server, name="delete_dt_server"),
    path("onboarding/", views.onboarding_wizard, name="onboarding_wizard"),
    # Backward compatibility redirects - must come before general patterns
    path("settings/", views.settings_redirect, name="settings_redirect"),
    path("<team_key>/settings/", views.team_settings_redirect, name="team_settings_redirect"),
    # Keep team_details as an alias that redirects to team_settings for backward compatibility
    path("<team_key>/details", views.team_details, name="team_details"),
    # Team settings pages
    path("<team_key>/settings/members/", views.team_members, name="team_members"),
    path("<team_key>/settings/branding/", views.team_branding, name="team_branding"),
    path("<team_key>/settings/integrations/", views.team_integrations, name="team_integrations"),
    path("<team_key>/settings/billing/", views.team_billing, name="team_billing"),
    path("<team_key>/settings/danger/", views.team_danger, name="team_danger"),
    # Main team settings (redirects to members) - must come after specific patterns
    path("<team_key>", views.team_settings, name="team_settings"),
]
