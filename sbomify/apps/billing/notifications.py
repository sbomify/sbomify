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


def get_notifications(request: HttpRequest) -> list[NotificationSchema]:
    """Main notification provider for billing app - handles all billing-related notifications"""
    notifications: list[NotificationSchema] = []

    # Skip all billing notifications if billing is disabled
    if not is_billing_enabled():
        return notifications

    if "current_team" not in request.session:
        return notifications

    team_key = request.session["current_team"]["key"]
    try:
        team = Team.objects.get(key=team_key)

        # Only show billing notifications to workspace owners
        if not team.members.filter(member__user=request.user, member__role="owner").exists():
            return notifications

        # Run all billing checks
        for check in [check_billing_plan_exists, check_billing_info_missing, check_payment_status]:
            if notification := check(team):
                notifications.append(notification)

    except Team.DoesNotExist:
        logger.warning(f"Workspace {team_key} not found when checking billing notifications")

    return notifications
