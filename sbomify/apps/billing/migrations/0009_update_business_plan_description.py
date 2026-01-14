# Generated manually to update business plan description
from django.db import migrations


def update_business_plan_description(apps, schema_editor):
    """Update business plan description from 'Pro plan' to 'Business plan'."""
    BillingPlan = apps.get_model("billing", "BillingPlan")
    business_plan = BillingPlan.objects.filter(key="business").first()
    if business_plan:
        business_plan.description = "Business plan for medium teams"
        business_plan.save(update_fields=["description"])


def reverse_update_business_plan_description(apps, schema_editor):
    """Reverse the description update."""
    BillingPlan = apps.get_model("billing", "BillingPlan")
    business_plan = BillingPlan.objects.filter(key="business").first()
    if business_plan:
        business_plan.description = "Pro plan for medium teams"
        business_plan.save(update_fields=["description"])


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0008_add_pricing_fields"),
    ]

    operations = [
        migrations.RunPython(
            update_business_plan_description,
            reverse_update_business_plan_description,
        ),
    ]

