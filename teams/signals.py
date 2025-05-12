from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone

from billing.models import BillingPlan
from billing.stripe_client import stripe_client
from core.utils import number_to_random_token
from sbomify.logging import getLogger

from .models import Member, Team

log = getLogger(__name__)


def get_team_name_for_user(user) -> str:
    """Get the team name for a user based on their profile information."""
    # Get user metadata from social auth
    social_account = SocialAccount.objects.filter(user=user).first()
    user_metadata = social_account.extra_data.get("user_metadata", {}) if social_account else {}
    company_name = user_metadata.get("company")

    if company_name:
        return company_name
    elif user.first_name:
        return f"{user.first_name}'s Team"
    else:
        return f"{user.username}'s Team"


@receiver(post_save, sender=get_user_model())
def create_team_for_user(sender, instance, created, **kwargs):
    """Create a team for a new user."""
    if created:
        with transaction.atomic():
            # Create default team
            default_team = Team(name=get_team_name_for_user(instance))
            default_team.save()

            # Set team key before creating membership
            default_team.key = number_to_random_token(default_team.pk)
            default_team.save()

            # Create team membership
            Member.objects.create(user=instance, team=default_team, role="owner", is_default_team=True)

        # Set up business plan trial
        try:
            # Get business plan
            business_plan = BillingPlan.objects.get(key="business")

            # Create Stripe customer
            customer = stripe_client.create_customer(
                email=instance.email, name=default_team.name, metadata={"team_key": default_team.key}
            )

            # Create subscription with trial
            subscription = stripe_client.create_subscription(
                customer_id=customer.id,
                price_id=business_plan.stripe_price_monthly_id,
                trial_days=settings.TRIAL_PERIOD_DAYS,
                metadata={"team_key": default_team.key, "plan_key": "business"},
            )

            # Update team with billing info
            default_team.billing_plan = "business"
            default_team.billing_plan_limits = {
                "max_products": business_plan.max_products,
                "max_projects": business_plan.max_projects,
                "max_components": business_plan.max_components,
                "stripe_customer_id": customer.id,
                "stripe_subscription_id": subscription.id,
                "subscription_status": "trialing",
                "is_trial": True,
                "trial_end": subscription.trial_end,
                "last_updated": timezone.now().isoformat(),
            }
            default_team.save()

            log.info(f"Created trial subscription for team {default_team.key} ({default_team.name})")

            # Send welcome email with plan limits from Stripe
            context = {
                "user": instance,
                "team": default_team,
                "base_url": settings.APP_BASE_URL,
                "TRIAL_PERIOD_DAYS": settings.TRIAL_PERIOD_DAYS,
                "trial_end_date": timezone.now() + timezone.timedelta(days=settings.TRIAL_PERIOD_DAYS),
                "plan_limits": {
                    "max_products": business_plan.max_products,
                    "max_projects": business_plan.max_projects,
                    "max_components": business_plan.max_components,
                },
            }
            send_mail(
                subject="Welcome to sbomify - Your Business Plan Trial",
                message=render_to_string("teams/new_user_email.txt", context),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[instance.email],
                html_message=render_to_string("teams/new_user_email.html", context),
            )
        except Exception as e:
            log.error(f"Failed to create trial subscription for team {default_team.key}: {str(e)}")
            # If trial setup fails, don't send the welcome email
            # The user can still set up billing later
