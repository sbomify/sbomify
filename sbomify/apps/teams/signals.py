import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_client import StripeClient
from sbomify.apps.core.utils import number_to_random_token

from .models import Member, Team, get_team_name_for_user

stripe_client = StripeClient()
logger = logging.getLogger(__name__)
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
            # Validate that user has an email address
            if not user.email:
                logger.error(f"User {user.username} has no email address, cannot create Stripe customer")
                raise ValueError("User must have an email address to create billing subscription")

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
            logger.info(f"Created trial subscription for team {team.key} ({team.name}) [post_save]")
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
                message=render_to_string("teams/emails/new_user_email.txt", context),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=render_to_string("teams/emails/new_user_email.html.j2", context),
            )
        except Exception as e:
            logger.error(f"Failed to create trial subscription for team {team.key} [post_save]: {str(e)}")
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


@receiver(post_save, sender=User)
def create_team_for_new_user(sender, instance, created, **kwargs):
    if created:
        ensure_user_has_team(instance)


# Store old role before save to detect role changes
_old_member_roles = {}


@receiver(pre_save, sender=Member)
def store_old_member_role(sender, instance, **kwargs):
    """Store the old role before saving to detect role changes."""
    if instance.pk:
        try:
            old_instance = Member.objects.only("role").get(pk=instance.pk)
            _old_member_roles[instance.pk] = old_instance.role
        except Member.DoesNotExist:
            # Member is new (no pk yet), no old role to store
            pass


@receiver(post_save, sender=Member)
def remove_access_requests_on_guest_upgrade(sender, instance, created, **kwargs):
    """Remove access requests when a guest user is upgraded to admin/owner."""
    if created:
        # New member, nothing to check
        return

    # Get the old role from our stored value
    old_role = _old_member_roles.pop(instance.pk, None)

    # If user is now admin/owner, check if they have access requests and remove them
    # This handles both cases:
    # 1. We know they were a guest (old_role == "guest")
    # 2. We don't know the old role but they have access requests (indicating they were likely a guest)
    if instance.role in ("admin", "owner"):
        try:
            from sbomify.apps.documents.access_models import AccessRequest
            from sbomify.apps.documents.views.access_requests import _invalidate_access_requests_cache

            # Check if they have access requests
            has_requests = AccessRequest.objects.filter(team=instance.team, user=instance.user).exists()

            # Remove if we know they were a guest, or if they have requests (likely were a guest)
            if old_role == "guest" or (old_role is None and has_requests):
                # Delete all access requests for this user in this team
                deleted_count = AccessRequest.objects.filter(team=instance.team, user=instance.user).delete()[0]
                if deleted_count > 0:
                    logger.info(
                        f"Removed {deleted_count} access request(s) for user {instance.user.email} "
                        f"in team {instance.team.key} after role upgrade to {instance.role}"
                    )
                    # Invalidate cache so the queue updates immediately
                    _invalidate_access_requests_cache(instance.team)
        except Exception as e:
            logger.error(
                f"Error removing access requests for user {instance.user.email} "
                f"in team {instance.team.key} after role upgrade: {e}",
                exc_info=True,
            )
