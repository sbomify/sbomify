from datetime import datetime

from django.urls import reverse
from ninja import Field, Router, Schema
from ninja.security import django_auth

from access_tokens.auth import PersonalAccessTokenAuth
from notifications.schemas import NotificationSchema
from sboms.models import Component, Product, Project
from sboms.utils import verify_item_access
from teams.models import Team

from .schemas import ErrorResponse


class RenameItemSchema(Schema):
    class Config(Schema.Config):
        str_strip_whitespace = True

    name: str = Field(..., max_length=255, min_length=1)


router = Router(tags=["core"], auth=(PersonalAccessTokenAuth(), django_auth))

item_type_map = {"team": Team, "component": Component, "project": Project, "product": Product}


@router.patch(
    "/rename/{item_type}/{item_id}",
    response={
        204: None,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
def rename_item(request, item_type: str, item_id: str, payload: RenameItemSchema):
    if item_type not in item_type_map:
        return 400, {"detail": "Invalid item type"}

    Model = item_type_map[item_type]

    if item_type == "team":
        rec = Team.objects.filter(key=item_id).first()
        permissions_required = ["owner"]
    else:
        rec = Model.objects.filter(id=item_id).first()
        permissions_required = ["owner", "admin"]

    if rec is None:
        return 404, {"detail": "Not found"}

    if not verify_item_access(request, rec, permissions_required):
        return 403, {"detail": "Forbidden"}

    rec.name = payload.name
    rec.save()

    return 204, None


@router.get(
    "/notifications",
    response={200: list[NotificationSchema], 403: ErrorResponse},
)
def get_notifications(request):
    """Get all active notifications for the current user and their active team."""
    notifications = []

    # Check if there's a current team in session
    if "current_team" in request.session:
        team_key = request.session["current_team"]["key"]
        try:
            team = Team.objects.get(key=team_key)

            # Check if billing is not set up
            if not team.billing_plan:
                # Create base notification
                notification = {
                    "id": "billing_required",
                    "type": "billing_required",
                    "message": "Please add your billing information to continue using premium features.",
                    "severity": "warning",
                    "created_at": "2024-01-20T12:00:00Z",  # This could be team creation date or current time
                }

                # Only add action URL if user is team owner
                if team.members.filter(member__user=request.user, member__role="owner").exists():
                    notification["action_url"] = reverse("billing:select_plan", kwargs={"team_key": team_key})

                notifications.append(notification)

            # Check for billing-related notifications
            if team.billing_plan == "business":
                subscription_status = team.billing_plan_limits.get("subscription_status")

                if subscription_status == "past_due":
                    # Add past due notification for team owners
                    if team.members.filter(member__user=request.user, member__role="owner").exists():
                        notification = {
                            "id": f"billing_past_due_{team.key}",
                            "type": "billing_past_due",
                            "message": "Your subscription payment is past due. Please update your payment information.",
                            "severity": "error",
                            "created_at": datetime.utcnow().isoformat(),
                            "action_url": reverse("billing:select_plan", kwargs={"team_key": team_key}),
                        }
                        notifications.append(notification)

                elif subscription_status == "canceled":
                    # Add cancellation notification for team owners
                    if team.members.filter(member__user=request.user, member__role="owner").exists():
                        notification = {
                            "id": f"billing_cancelled_{team.key}",
                            "type": "billing_cancelled",
                            "message": "Your subscription has been cancelled and will end at the end "
                            "of the billing period.",
                            "severity": "warning",
                            "created_at": datetime.utcnow().isoformat(),
                            "action_url": reverse("billing:select_plan", kwargs={"team_key": team_key}),
                        }
                        notifications.append(notification)

        except Team.DoesNotExist:
            pass  # If team doesn't exist, no notifications

    return notifications
