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
    path("<team_key>/settings", views.team_settings, name="team_settings"),
    path("<team_key>", views.team_details, name="team_details"),
    path("onboarding/", views.onboarding_wizard, name="onboarding_wizard"),
]
