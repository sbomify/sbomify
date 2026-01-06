# Generated migration for adding pricing fields to BillingPlan

from django.conf import settings
from django.db import migrations, models
import sys

PRICE_PLANS = {
    'business': {
        'annual': 159 * 12,
        'monthly': 199,
    }
}


def is_test_environment():
    """Helper to check if we're in test environment."""
    is_test = any([
        not getattr(settings, 'STRIPE_SECRET_KEY', None),
        getattr(settings, 'STRIPE_SECRET_KEY', '') == 'sk_test_dummy_key_for_ci',
        getattr(settings, 'DJANGO_TEST', False),
        getattr(settings, 'TESTING', False),
        'test' in settings.DATABASES['default']['NAME'],
        'pytest' in sys.modules,
    ])
    return is_test


def populate_pricing_fields(apps, schema_editor):
    """Populate monthly_price and annual_price from Stripe or fallback to PRICE_PLANS."""
    BillingPlan = apps.get_model('billing', 'BillingPlan')
    
    # Skip in test environments
    if is_test_environment():
        print("Skipping price population in test/CI environment")  # noqa: T201
        # Set default values for test
        for plan in BillingPlan.objects.all():
            if plan.key in PRICE_PLANS:
                plan.monthly_price = PRICE_PLANS[plan.key]['monthly']
                plan.annual_price = PRICE_PLANS[plan.key]['annual']
                plan.save()
        return

    # Try to fetch from Stripe
    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        for plan in BillingPlan.objects.all():
            updated = False
            
            # Fetch monthly price from Stripe
            if plan.stripe_price_monthly_id:
                try:
                    stripe_price = stripe.Price.retrieve(plan.stripe_price_monthly_id)
                    if stripe_price.unit_amount:
                        plan.monthly_price = stripe_price.unit_amount / 100
                        updated = True
                        print(f"Fetched monthly price ${plan.monthly_price} from Stripe for {plan.key}")  # noqa: T201
                except stripe.error.StripeError as e:
                    print(f"Failed to fetch monthly price from Stripe for {plan.key}: {str(e)}")  # noqa: T201
                    # Fall back to PRICE_PLANS if available
                    if plan.key in PRICE_PLANS:
                        plan.monthly_price = PRICE_PLANS[plan.key]['monthly']
                        updated = True
                        print(f"Using fallback monthly price ${plan.monthly_price} for {plan.key}")  # noqa: T201
            
            # Fetch annual price from Stripe
            if plan.stripe_price_annual_id:
                try:
                    stripe_price = stripe.Price.retrieve(plan.stripe_price_annual_id)
                    if stripe_price.unit_amount:
                        plan.annual_price = stripe_price.unit_amount / 100
                        updated = True
                        print(f"Fetched annual price ${plan.annual_price} from Stripe for {plan.key}")  # noqa: T201
                except stripe.error.StripeError as e:
                    print(f"Failed to fetch annual price from Stripe for {plan.key}: {str(e)}")  # noqa: T201
                    # Fall back to PRICE_PLANS if available
                    if plan.key in PRICE_PLANS:
                        plan.annual_price = PRICE_PLANS[plan.key]['annual']
                        updated = True
                        print(f"Using fallback annual price ${plan.annual_price} for {plan.key}")  # noqa: T201
            
            # Use PRICE_PLANS fallback if Stripe IDs exist but prices weren't fetched
            if not updated and plan.key in PRICE_PLANS:
                if plan.stripe_price_monthly_id and plan.monthly_price is None:
                    plan.monthly_price = PRICE_PLANS[plan.key]['monthly']
                    updated = True
                if plan.stripe_price_annual_id and plan.annual_price is None:
                    plan.annual_price = PRICE_PLANS[plan.key]['annual']
                    updated = True
            
            if updated:
                plan.save()
                
    except ImportError:
        print("Stripe not available, using PRICE_PLANS fallback")  # noqa: T201
        for plan in BillingPlan.objects.all():
            if plan.key in PRICE_PLANS:
                plan.monthly_price = PRICE_PLANS[plan.key]['monthly']
                plan.annual_price = PRICE_PLANS[plan.key]['annual']
                plan.save()
    except Exception as e:
        print(f"Error populating prices: {str(e)}")  # noqa: T201
        # Fall back to PRICE_PLANS
        for plan in BillingPlan.objects.all():
            if plan.key in PRICE_PLANS:
                plan.monthly_price = PRICE_PLANS[plan.key]['monthly']
                plan.annual_price = PRICE_PLANS[plan.key]['annual']
                plan.save()


def reverse_populate_pricing_fields(apps, schema_editor):
    """Reverse migration - set prices to None."""
    BillingPlan = apps.get_model('billing', 'BillingPlan')
    for plan in BillingPlan.objects.all():
        plan.monthly_price = None
        plan.annual_price = None
        plan.save()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0007_ensure_existing_teams_comply_with_user_limits'),
    ]

    operations = [
        migrations.AddField(
            model_name='billingplan',
            name='monthly_price',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='The cost per month for monthly billing (Display only - must match Stripe).', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='billingplan',
            name='annual_price',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='The cost per year for annual billing (Display only - must match Stripe).', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='billingplan',
            name='discount_percent_monthly',
            field=models.IntegerField(default=0, help_text='Promotional discount percentage for monthly billing.'),
        ),
        migrations.AddField(
            model_name='billingplan',
            name='discount_percent_annual',
            field=models.IntegerField(default=0, help_text='Promotional discount percentage for annual billing.'),
        ),
        migrations.AddField(
            model_name='billingplan',
            name='promo_message',
            field=models.CharField(blank=True, help_text='Optional promotional message to display.', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='billingplan',
            name='last_synced_at',
            field=models.DateTimeField(blank=True, help_text='Timestamp of last Stripe price sync.', null=True),
        ),
        migrations.RunPython(populate_pricing_fields, reverse_populate_pricing_fields),
    ]

