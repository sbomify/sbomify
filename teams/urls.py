from django.urls import path
from django.urls.resolvers import URLPattern

from . import views

app_name = "teams"
urlpatterns: list[URLPattern] = [
    path(app_name + "/", views.teams_dashboard, name="teams_dashboard"),
    path(app_name + "/switch/<team_key>/", views.switch_team, name="switch_team"),
    path(app_name + "/set_default/<membership_id>/", views.set_default_team, name="set_default_team"),
    path(app_name + "/delete/<team_key>/", views.delete_team, name="delete_team"),
    path(app_name + "/invite/<team_key>/", views.invite, name="invite_user"),
    path(app_name + "/accept_invite/<invite_id>/", views.accept_invite, name="accept_invite"),
    path(app_name + "/<membership_id>/leave", views.delete_member, name="team_membership_delete"),
    path(app_name + "/<invitation_id>/uninvite", views.delete_invite, name="team_invitation_delete"),
    path(app_name + "/<team_key>/settings", views.team_settings, name="team_settings"),
    path(app_name + "/<team_key>", views.team_details, name="team_details"),
    path("onboarding/", views.onboarding_wizard, name="onboarding_wizard"),
]
