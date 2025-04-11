import stripe
from django.apps import AppConfig
from django.conf import settings


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "billing"

    def ready(self):
        if settings.BILLING_MODE == "disabled":
            # Don't set up stripe at all
            return

        if settings.BILLING_MODE == "development":
            # Use test key for development
            stripe.api_key = "sk_test_dummy_key_for_ci"
            return

        # Production mode - use real stripe key
        stripe.api_key = settings.STRIPE_API_KEY
