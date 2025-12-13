from django.urls import path
from django.urls.resolvers import URLPattern

from . import views

app_name = "billing"
urlpatterns: list[URLPattern] = [
    # path(app_name + "/", views.teams_dashboard, name="billing_dashboard"),
    path("select-initial-plan/", views.initial_plan_selection, name="initial_plan_selection"),
    path("select-plan/<str:team_key>", views.select_plan, name="select_plan"),
    path("enterprise-contact/", views.enterprise_contact, name="enterprise_contact"),
    path("billing-redirect/<str:team_key>", views.billing_redirect, name="billing_redirect"),
    path("return", views.billing_return, name="billing_return"),
    path("checkout/success/", views.checkout_success, name="checkout_success"),
    path("checkout/cancel/", views.checkout_cancel, name="checkout_cancel"),
    path("webhook/", views.stripe_webhook, name="webhook"),
]
