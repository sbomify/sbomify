from django.urls import path
from django.urls.resolvers import URLPattern

from . import views

app_name = "billing"
urlpatterns: list[URLPattern] = [
    # path(app_name + "/", views.teams_dashboard, name="billing_dashboard"),
    path("select-plan/<str:team_key>", views.select_plan, name="select_plan"),
    path("billing-redirect/<str:team_key>", views.billing_redirect, name="billing_redirect"),
    path("return", views.billing_return, name="billing_return"),
    path("webhook/", views.stripe_webhook, name="webhook"),
]
