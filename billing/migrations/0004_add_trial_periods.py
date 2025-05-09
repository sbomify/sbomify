"""
This migration adds trial periods to existing Stripe prices.
"""

from django.conf import settings
from django.db import migrations
import stripe
import sys


def is_test_environment():
    """Helper to check if we're in test environment."""
    # Check for test environment indicators
    is_test = any([
        not getattr(settings, 'STRIPE_SECRET_KEY', None),  # Check if setting exists
        getattr(settings, 'STRIPE_SECRET_KEY', '') == 'sk_test_dummy_key_for_ci',
        getattr(settings, 'DJANGO_TEST', False),  # Check explicit test flag
        getattr(settings, 'TESTING', False),  # Check Django's test flag
        'test' in settings.DATABASES['default']['NAME'],
        'pytest' in sys.modules,
    ])

    if is_test:
        # Ensure stripe is not imported
        if 'stripe' in sys.modules:
            del sys.modules['stripe']
            # Also clear any cached API key
            import importlib
            if 'stripe.api_key' in sys.modules:
                del sys.modules['stripe.api_key']
    return is_test


def add_trial_periods(apps, schema_editor):
    """Add trial periods to existing Stripe prices."""
    # First thing: check test environment
    if is_test_environment():
        print("Skipping trial period setup in test/CI environment")
        return

    if not settings.STRIPE_SECRET_KEY:
        print("No Stripe API key found, skipping trial period setup")
        return

    BillingPlan = apps.get_model('billing', 'BillingPlan')
    stripe.api_key = settings.STRIPE_SECRET_KEY

    for plan in BillingPlan.objects.filter(stripe_product_id__isnull=False):
        # Update monthly price
        if plan.stripe_price_monthly_id:
            try:
                stripe.Price.modify(
                    plan.stripe_price_monthly_id,
                    recurring={'trial_period_days': settings.TRIAL_PERIOD_DAYS}
                )
                print(f"Added trial period to monthly price for {plan.key}")
            except stripe.error.StripeError as e:
                print(f"Error updating monthly price for {plan.key}: {str(e)}")

        # Update annual price
        if plan.stripe_price_annual_id:
            try:
                stripe.Price.modify(
                    plan.stripe_price_annual_id,
                    recurring={'trial_period_days': settings.TRIAL_PERIOD_DAYS}
                )
                print(f"Added trial period to annual price for {plan.key}")
            except stripe.error.StripeError as e:
                print(f"Error updating annual price for {plan.key}: {str(e)}")


def reverse_trial_periods(apps, schema_editor):
    """This is a one-way migration - we can't remove trial periods from prices."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0003_setup_stripe_billing'),
    ]

    operations = [
        migrations.RunPython(add_trial_periods, reverse_trial_periods),
    ]