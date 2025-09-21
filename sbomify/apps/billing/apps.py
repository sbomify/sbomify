import stripe
from django.apps import AppConfig
from django.conf import settings


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.billing"
    label = "billing"

    def ready(self):
        # Only set Stripe API key if billing is enabled
        if getattr(settings, "BILLING", True):
            # This ensures stripe.api_key is set when Django starts
            # It will use the value from STRIPE_SECRET_KEY environment variable
            stripe.api_key = settings.STRIPE_API_KEY
