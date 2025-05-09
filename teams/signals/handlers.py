from __future__ import annotations

import logging
import typing

if typing.TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import Model
    from django.http import HttpRequest

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone
from social_django.models import UserSocialAuth

from billing.models import BillingPlan
from billing.stripe_client import StripeClient
from core.utils import number_to_random_token
from teams.utils import get_user_teams

from ..models import Member, Team, get_team_name_for_user

log = logging.getLogger(__name__)
stripe_client = StripeClient()


@receiver(user_logged_in)
def user_logged_in_handler(sender: Model, user: User, request: HttpRequest, **kwargs):
    request.session["user_photo"] = ""
    social_record = UserSocialAuth.objects.filter(user=user).first()
    if social_record:
        request.session["user_photo"] = social_record.extra_data.get("picture", "")

    # Get user teams and store them in session
    user_teams = get_user_teams(user)
    request.session["user_teams"] = user_teams

    if request.session.get("current_team", None) is None and user_teams:
        for team_key, team_data in user_teams.items():
            if team_data["is_default_team"]:
                first_team = {"key": team_key, **team_data}
                request.session["current_team"] = first_team
                break


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def new_user_handler(sender: Model, instance: User, created: bool, **kwargs):
    if created:
        with transaction.atomic():
            # Create default team
            default_team = Team(name=get_team_name_for_user(instance))
            default_team.save()

            default_team.key = number_to_random_token(default_team.pk)
            default_team.save()

            # Create team membership
            team_membership = Member(user=instance, team=default_team, role="owner", is_default_team=True)
            team_membership.save()

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
                    "membership": team_membership,
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
