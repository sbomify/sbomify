import logging
from typing import Any

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialLogin
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.utils import timezone

from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_client import StripeClient
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team

logger = logging.getLogger(__name__)
User = get_user_model()
stripe_client = StripeClient()


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom social account adapter for Keycloak authentication."""

    def pre_social_login(self, request: HttpRequest, sociallogin: SocialLogin) -> None:
        """
        Handle user account connecting or creation.

        Args:
            request: The current HTTP request
            sociallogin: The social login instance
        """
        logger.debug(f"Pre-social login: {sociallogin.account.provider} - {sociallogin.account.uid}")
        logger.debug(f"Extra data: {sociallogin.account.extra_data}")

        # If we found an existing user with the same email
        existing_user = sociallogin.user
        if existing_user.id is None and existing_user.email:
            try:
                existing_user = User.objects.get(email=existing_user.email)
                sociallogin.connect(request, existing_user)
            except User.DoesNotExist:
                pass

    def populate_user(self, request: HttpRequest, sociallogin: SocialLogin, data: dict[str, Any]) -> Any:
        """
        Populate user instance with data from social account.

        Creates a username from the email address by replacing @ with . to ensure uniqueness.
        Also handles Keycloak-specific data like email verification status.

        Args:
            request: The current HTTP request
            sociallogin: The social login instance being processed
            data: The user data from the social provider

        Returns:
            The populated user instance
        """
        user = super().populate_user(request, sociallogin, data)
        logger.debug(f"Populating user with data: {data}")

        # Handle Keycloak-specific data
        if sociallogin.account.provider == "keycloak":
            # Set email verification status
            user.is_active = True  # Keycloak handles activation
            user.email_verified = data.get("email_verified", False)

            # Map Keycloak name fields directly to Django fields (try both possible keys)
            user.first_name = data.get("given_name") or data.get("first_name", "")
            user.last_name = data.get("family_name") or data.get("last_name", "")

            # Use preferred_username if available
            if "preferred_username" in data:
                user.username = data["preferred_username"]
                return user  # Skip email-based username generation

        if user.email:
            # Create username from email (e.g., "kashif@compulife.com.pk" -> "kashif.compulife.com.pk")
            username = user.email.replace("@", ".")

            # Ensure username is unique
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1

            user.username = username
            logger.debug(f"Generated username: {username}")

        return user

    def is_auto_signup_allowed(self, request: HttpRequest, sociallogin: SocialLogin) -> bool:
        """
        Indicates whether the user should be automatically signed up.

        Always returns True to skip the signup form and create the user automatically.

        Args:
            request: The current HTTP request
            sociallogin: The social login instance being processed

        Returns:
            True to enable automatic signup
        """
        return True

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)

        # Ensure email is set from sociallogin if not already present
        # This is done before team creation to ensure email is available for billing
        if not user.email and sociallogin.account.extra_data:
            email = sociallogin.account.extra_data.get("email")
            if email:
                # Validate and sanitize email
                from django.core.exceptions import ValidationError as DjangoValidationError
                from django.core.validators import EmailValidator

                email = email.strip()
                validator = EmailValidator()
                try:
                    validator(email)
                    user.email = email
                    user.save(update_fields=["email"])
                    logger.info(f"Set email from social account for user {user.username}: {email}")
                except DjangoValidationError:
                    logger.warning(f"Invalid email from social account for user {user.username}: {email}")

        # Only create a team if this is a new user and they have no teams
        if not Team.objects.filter(members=user).exists():
            first_name = user.first_name or user.username.split("@")[0]
            team_name = f"{first_name}'s Workspace"
            with transaction.atomic():
                team = Team.objects.create(name=team_name)
                team.key = number_to_random_token(team.pk)
                team.save()
                Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

            # Set up billing plan - either trial subscription if billing enabled, or community plan if disabled
            if is_billing_enabled():
                # Set up business plan trial
                try:
                    # Validate that user has an email address
                    if not user.email:
                        logger.error(f"User {user.username} has no email address, cannot create Stripe customer")
                        raise ValueError("User must have an email address to create billing subscription")

                    business_plan = BillingPlan.objects.get(key="business")
                    customer = stripe_client.create_customer(
                        email=user.email, name=team.name, metadata={"team_key": team.key}
                    )
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
                    logger.info(f"Created trial subscription for team {team.key} ({team.name})")
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
                    logger.error(f"Failed to create trial subscription for team {team.key}: {str(e)}")
                    # Fallback: Set up community plan so user can still use the system
                    try:
                        logger.info(f"Falling back to community plan for team {team.key}")
                        community_plan = BillingPlan.objects.get(key="community")
                        team.billing_plan = "community"
                        team.billing_plan_limits = {
                            "max_products": community_plan.max_products,
                            "max_projects": community_plan.max_projects,
                            "max_components": community_plan.max_components,
                            "subscription_status": "active",
                            "last_updated": timezone.now().isoformat(),
                        }
                        team.save()
                        logger.info(f"Set up community plan fallback for team {team.key} ({team.name})")
                    except BillingPlan.DoesNotExist:
                        logger.error(f"Could not set up fallback plan for team {team.key} - no community plan exists")
            else:
                # Billing is disabled, set up community plan with unlimited limits
                try:
                    community_plan = BillingPlan.objects.get(key="community")
                    team.billing_plan = "community"
                    team.billing_plan_limits = {
                        "max_products": community_plan.max_products,
                        "max_projects": community_plan.max_projects,
                        "max_components": community_plan.max_components,
                        "subscription_status": "active",
                        "last_updated": timezone.now().isoformat(),
                    }
                    team.save()
                    logger.info(f"Set up community plan for team {team.key} ({team.name}) - billing disabled")
                except BillingPlan.DoesNotExist:
                    # Fallback to unlimited limits if community plan doesn't exist
                    from sbomify.apps.billing.config import get_unlimited_plan_limits

                    team.billing_plan = "community"
                    team.billing_plan_limits = get_unlimited_plan_limits()
                    team.billing_plan_limits["last_updated"] = timezone.now().isoformat()
                    team.save()
                    logger.info(
                        f"Set up unlimited plan for team {team.key} ({team.name}) - "
                        f"billing disabled, no community plan found"
                    )
        return user
