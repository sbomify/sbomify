import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone

from billing.models import BillingPlan
from billing.stripe_client import StripeClient
from core.utils import number_to_random_token

from .models import Member, Team, get_team_name_for_user

stripe_client = StripeClient()
log = logging.getLogger(__name__)
User = get_user_model()


def ensure_user_has_team(user):
    if not Team.objects.filter(members=user).exists():
        team_name = get_team_name_for_user(user)
        with transaction.atomic():
            team = Team.objects.create(name=team_name)
            team.key = number_to_random_token(team.pk)
            team.save()
            Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        # Set up business plan trial
        try:
            business_plan = BillingPlan.objects.get(key="business")
            customer = stripe_client.create_customer(email=user.email, name=team.name, metadata={"team_key": team.key})
            subscription = stripe_client.create_subscription(
                customer_id=customer.id,
                price_id=business_plan.stripe_price_monthly_id,
                trial_days=settings.TRIAL_PERIOD_DAYS,
                metadata={"team_key": team.key, "plan_key": "business"},
            )
            team.billing_plan = "business"
            team.billing_plan_limits = {
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
            team.save()
            log.info(f"Created trial subscription for team {team.key} ({team.name}) [post_save]")
            context = {
                "user": user,
                "team": team,
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
                recipient_list=[user.email],
                html_message=render_to_string("teams/new_user_email.html.j2", context),
            )
        except Exception as e:
            log.error(f"Failed to create trial subscription for team {team.key} [post_save]: {str(e)}")


@receiver(post_save, sender=User)
def create_team_for_new_user(sender, instance, created, **kwargs):
    if created:
        ensure_user_has_team(instance)
