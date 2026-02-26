"""
Module for billing-related UI notifications
"""

from datetime import datetime

from django.db import transaction
from django.http import HttpRequest
from django.urls import reverse

from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_cache import get_subscription_cancel_at_period_end, invalidate_subscription_cache
from sbomify.apps.core.queries import get_team_asset_counts
from sbomify.apps.notifications.schemas import NotificationSchema
from sbomify.apps.teams.models import Team
from sbomify.logging import getLogger

logger = getLogger(__name__)


def check_billing_plan_exists(team: Team) -> NotificationSchema | None:
    """Check if a workspace has a billing plan selected"""
    if not team.billing_plan:
        return NotificationSchema(
            id=f"workspace_billing_required_{team.key}",
            type="workspace_billing_required",
            message="Please add your billing information to continue using premium features.",
            severity="warning",
            created_at=datetime.utcnow().isoformat(),
            action_url=reverse("billing:select_plan", kwargs={"team_key": team.key}),
        )
    return None


def check_billing_info_missing(team: Team) -> NotificationSchema | None:
    """Check if billing information is missing for business plan"""
    billing_limits = team.billing_plan_limits or {}
    if team.billing_plan == "business" and not billing_limits.get("stripe_customer_id"):
        return NotificationSchema(
            id=f"billing_add_billing_{team.key}",
            type="billing_add_billing",
            message="Please add your billing information to continue using premium features",
            severity="warning",
            created_at=datetime.utcnow().isoformat(),
            action_url=reverse("billing:select_plan", kwargs={"team_key": team.key}),
        )
    return None


def check_payment_status(team: Team) -> NotificationSchema | None:
    """Check subscription payment status"""
    if team.billing_plan != "business":
        return None

    billing_limits = team.billing_plan_limits or {}
    subscription_status = billing_limits.get("subscription_status")
    downgrade_exceeded = billing_limits.get("downgrade_exceeded", False)

    if subscription_status == "past_due":
        if downgrade_exceeded:
            return NotificationSchema(
                id=f"billing_downgrade_blocked_{team.key}",
                type="billing_downgrade_blocked",
                message=(
                    "Your downgrade was blocked because your current usage exceeds the Community plan limits. "
                    "Please reduce your usage or continue with your current plan to avoid service interruption."
                ),
                severity="error",
                created_at=datetime.utcnow().isoformat(),
                action_url=reverse("billing:select_plan", kwargs={"team_key": team.key}),
            )
        else:
            return NotificationSchema(
                id=f"billing_payment_past_due_{team.key}",
                type="billing_payment_past_due",
                message="Your subscription payment is past due. Please update your payment information.",
                severity="error",
                created_at=datetime.utcnow().isoformat(),
                action_url=reverse("billing:select_plan", kwargs={"team_key": team.key}),
            )
    elif subscription_status == "canceled":
        return NotificationSchema(
            id=f"billing_subscription_cancelled_{team.key}",
            type="billing_subscription_cancelled",
            message="Your subscription has been cancelled and will end at the end of the billing period.",
            severity="warning",
            created_at=datetime.utcnow().isoformat(),
            action_url=reverse("billing:select_plan", kwargs={"team_key": team.key}),
        )
    return None


def check_downgrade_limit_exceeded(team: Team) -> NotificationSchema | None:
    """Check if scheduled downgrade would exceed target plan limits"""
    if not is_billing_enabled():
        return None

    billing_limits = team.billing_plan_limits or {}
    cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)
    scheduled_downgrade_plan = billing_limits.get("scheduled_downgrade_plan", "community")
    stripe_subscription_id = billing_limits.get("stripe_subscription_id")

    if not cancel_at_period_end or not scheduled_downgrade_plan:
        return None

    # Fetch real-time subscription data from Stripe to verify cancel_at_period_end status
    real_cancel_at_period_end = get_subscription_cancel_at_period_end(
        stripe_subscription_id, team.key, fallback_value=cancel_at_period_end
    )

    # If user cancelled the cancellation (reactivated subscription)
    if not real_cancel_at_period_end:
        invalidate_subscription_cache(stripe_subscription_id, team.key)
        with transaction.atomic():
            team = Team.objects.select_for_update().get(pk=team.pk)
            billing_limits = (team.billing_plan_limits or {}).copy()
            billing_limits.pop("scheduled_downgrade_plan", None)
            team.billing_plan_limits = billing_limits
            team.save()
        logger.info("User reactivated subscription, cleared scheduled downgrade")
        return None

    # Still scheduled, check if usage exceeds target plan limits
    try:
        target_plan = BillingPlan.objects.get(key=scheduled_downgrade_plan)
    except BillingPlan.DoesNotExist:
        logger.warning("Target plan not found for scheduled downgrade")
        return None

    counts = get_team_asset_counts(team.id)
    product_count = counts["products"]
    project_count = counts["projects"]
    component_count = counts["components"]

    # Check if any limit is exceeded
    usage_exceeds_limits = False

    if target_plan.max_products is not None and product_count > target_plan.max_products:
        usage_exceeds_limits = True
    elif target_plan.max_projects is not None and project_count > target_plan.max_projects:
        usage_exceeds_limits = True
    elif target_plan.max_components is not None and component_count > target_plan.max_components:
        usage_exceeds_limits = True

    if usage_exceeds_limits:
        return NotificationSchema(
            id=f"billing_downgrade_limit_exceeded_{team.key}",
            type="billing_downgrade_limit_exceeded",
            message=(
                f"You cannot downgrade because your current usage exceeds the {target_plan.name} plan limits. "
                "Please reduce your usage or continue with your current plan."
            ),
            severity="error",
            created_at=datetime.utcnow().isoformat(),
            action_url=reverse("billing:select_plan", kwargs={"team_key": team.key}),
        )

    return None


def check_community_upgrade(team: Team) -> NotificationSchema | None:
    """Check if community plan user should upgrade to paid plan"""
    # Show upgrade notification if billing_plan is None or "community"
    billing_plan = team.billing_plan

    # If billing_plan is None or empty string, show upgrade notification
    if not billing_plan or (isinstance(billing_plan, str) and not billing_plan.strip()):
        logger.debug("Returning upgrade notification for team (billing_plan is None/empty)")
        return NotificationSchema(
            id=f"community_upgrade_{team.key}",
            type="community_upgrade",
            message="Upgrade to a paid plan to unlock more features and remove limitations.",
            severity="info",
            created_at=datetime.utcnow().isoformat(),
            action_url=reverse("billing:select_plan", kwargs={"team_key": team.key}),
        )

    # If billing_plan is "community", show upgrade notification
    if isinstance(billing_plan, str) and billing_plan.strip().lower() == "community":
        logger.debug("Returning upgrade notification for team (billing_plan is 'community')")
        return NotificationSchema(
            id=f"community_upgrade_{team.key}",
            type="community_upgrade",
            message="Upgrade to a paid plan to unlock more features and remove limitations.",
            severity="info",
            created_at=datetime.utcnow().isoformat(),
            action_url=reverse("billing:select_plan", kwargs={"team_key": team.key}),
        )

    return None


def get_notifications(request: HttpRequest) -> list[NotificationSchema]:
    """Main notification provider for billing app - handles all billing-related notifications"""
    notifications: list[NotificationSchema] = []

    if "current_team" not in request.session:
        logger.debug("No current_team in session, skipping notifications")
        return notifications

    team_key = request.session["current_team"]["key"]
    logger.debug("get_notifications called for team")
    try:
        team = Team.objects.get(key=team_key)
        logger.debug("Checking notifications for team")

        # Check if user is a member of this team
        from sbomify.apps.teams.models import Member

        user_member = Member.objects.filter(team=team, user=request.user).first()

        if not user_member:
            # User is not a member, don't show notifications
            logger.debug("User is not a member of team")
            return notifications

        # Check if user is workspace owner
        is_owner = user_member.role == "owner"
        logger.debug("User is %s owner of team", "not" if not is_owner else "")

        # Only run billing-specific checks if billing is enabled
        if is_billing_enabled():
            # Run billing checks - upgrade notification shown to all users, others only to owners
            if is_owner:
                for check in [
                    check_billing_plan_exists,
                    check_billing_info_missing,
                    check_payment_status,
                    check_downgrade_limit_exceeded,
                ]:
                    if notification := check(team):
                        notifications.append(notification)
                        logger.debug("Added notification: %s", notification.type)

        # Upgrade notification shown to all users (if on community plan or no plan)
        if is_billing_enabled():
            upgrade_notification = check_community_upgrade(team)
            logger.debug("check_community_upgrade result: %s", upgrade_notification is not None)
            if upgrade_notification:
                notifications.append(upgrade_notification)
                logger.debug("Added upgrade notification for team")
            else:
                logger.debug("No upgrade notification for team")

    except Team.DoesNotExist:
        logger.debug("Workspace not found when checking billing notifications")
    except Exception as e:
        logger.exception("Error checking notifications for team: %s", str(e))

    logger.debug("Returning %d notifications for team", len(notifications))
    return notifications
