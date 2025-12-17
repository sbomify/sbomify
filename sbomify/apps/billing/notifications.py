"""
Module for billing-related UI notifications
"""

from datetime import datetime

from django.http import HttpRequest
from django.urls import reverse

from sbomify.apps.billing.config import is_billing_enabled
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
    if team.billing_plan == "business" and not team.billing_plan_limits.get("stripe_customer_id"):
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

    subscription_status = team.billing_plan_limits.get("subscription_status")
    if subscription_status == "past_due":
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


def check_community_upgrade(team: Team) -> NotificationSchema | None:
    """Check if community plan user should upgrade to paid plan"""
    # Show upgrade notification if billing_plan is None or "community"
    billing_plan = team.billing_plan
    logger.warning(
        f"check_community_upgrade: team={team.key}, billing_plan={repr(billing_plan)}, type={type(billing_plan)}"
    )

    # If billing_plan is None or empty string, show upgrade notification
    if not billing_plan or (isinstance(billing_plan, str) and not billing_plan.strip()):
        logger.warning(f"Returning upgrade notification for team {team.key} (billing_plan is None/empty)")
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
        logger.warning(f"Returning upgrade notification for team {team.key} (billing_plan is 'community')")
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
        logger.warning("No current_team in session, skipping notifications")
        return notifications

    team_key = request.session["current_team"]["key"]
    logger.warning(f"get_notifications called for team_key={team_key}, user={request.user.id}")
    try:
        team = Team.objects.get(key=team_key)
        logger.warning(f"Checking notifications for team {team.key}, billing_plan: {repr(team.billing_plan)}")

        # Check if user is a member of this team
        from sbomify.apps.teams.models import Member

        user_member = Member.objects.filter(team=team, user=request.user).first()

        if not user_member:
            # User is not a member, don't show notifications
            logger.warning(f"User {request.user.id} is not a member of team {team.key}")
            return notifications

        # Check if user is workspace owner
        is_owner = user_member.role == "owner"
        logger.warning(f"User {request.user.id} is {'owner' if is_owner else 'not owner'} of team {team.key}")

        # Only run billing-specific checks if billing is enabled
        if is_billing_enabled():
            # Run billing checks - upgrade notification shown to all users, others only to owners
            if is_owner:
                for check in [check_billing_plan_exists, check_billing_info_missing, check_payment_status]:
                    if notification := check(team):
                        notifications.append(notification)
                        logger.warning(f"Added notification: {notification.type}")

        # Upgrade notification shown to all users (if on community plan or no plan)
        # This check runs regardless of billing being enabled/disabled
        upgrade_notification = check_community_upgrade(team)
        logger.warning(f"check_community_upgrade result for team {team.key}: {upgrade_notification is not None}")
        if upgrade_notification:
            notifications.append(upgrade_notification)
            logger.warning(f"Added upgrade notification for team {team.key} (billing_plan: {repr(team.billing_plan)})")
        else:
            logger.warning(f"No upgrade notification for team {team.key} (billing_plan: {repr(team.billing_plan)})")

    except Team.DoesNotExist:
        logger.warning(f"Workspace {team_key} not found when checking billing notifications")
    except Exception as e:
        logger.exception(f"Error checking notifications for team {team_key}: {str(e)}")

    logger.warning(f"Returning {len(notifications)} notifications for team {team_key}")
    return notifications
