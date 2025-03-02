import stripe
from django.apps import AppConfig
from django.conf import settings


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "billing"

    def ready(self):
        # This ensures stripe.api_key is set when Django starts
        # It will use the value from STRIPE_SECRET_KEY environment variable
        stripe.api_key = settings.STRIPE_API_KEY
