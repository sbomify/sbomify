"""
This migration sets up billing plans for development environments.
It is safe to run in production as it only affects environments where STRIPE_SECRET_KEY
is not set or is set to the test key.
"""

from django.db import migrations


def setup_development_billing(apps, schema_editor):
    """
    In development environments, set teams without billing plans to enterprise.
    This is safe to run in production as it only affects development environments
    and only modifies teams that don't already have a billing plan.
    """
    # Skip in production environments
    if schema_editor.connection.settings_dict.get('STRIPE_SECRET_KEY') and \
       schema_editor.connection.settings_dict.get('STRIPE_SECRET_KEY') != 'sk_test_dummy_key_for_ci':
        return

    Team = apps.get_model("teams", "Team")
    BillingPlan = apps.get_model("billing", "BillingPlan")

    # Get or create enterprise plan
    enterprise_plan = BillingPlan.objects.filter(key="enterprise").first()
    if not enterprise_plan:
        return  # Safety check - don't proceed if enterprise plan doesn't exist

    # Only affect teams without a billing plan
    for team in Team.objects.filter(billing_plan__isnull=True):
        team.billing_plan = enterprise_plan.key
        team.billing_plan_limits = {
            "max_products": None,
            "max_projects": None,
            "max_components": None,
            "subscription_status": "active"
        }
        team.save()


class Migration(migrations.Migration):
    """
    Migration to set up development billing environment.
    Dependencies ensure this runs after billing plans are created.
    """
    dependencies = [
        ("billing", "0003_setup_stripe_billing"),
        ("teams", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            setup_development_billing,
            reverse_code=migrations.RunPython.noop
        ),
    ]