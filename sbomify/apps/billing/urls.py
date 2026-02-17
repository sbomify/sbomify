from django.urls import path
from django.urls.resolvers import URLPattern

from . import views

app_name = "billing"
urlpatterns: list[URLPattern] = [
    path("redirect/<str:team_key>/", views.BillingRedirectView.as_view(), name="billing_redirect"),
    path("portal/<str:team_key>/", views.CreatePortalSessionView.as_view(), name="create_portal_session"),
    path("select-plan/<str:team_key>/", views.SelectPlanView.as_view(), name="select_plan"),
    path("enterprise-contact/", views.EnterpriseContactView.as_view(), name="enterprise_contact"),
    path("return/", views.BillingReturnView.as_view(), name="billing_return"),
    path("checkout/success/", views.CheckoutSuccessView.as_view(), name="checkout_success"),
    path("checkout/cancel/", views.CheckoutCancelView.as_view(), name="checkout_cancel"),
    path("webhook/", views.StripeWebhookView.as_view(), name="webhook"),
]
