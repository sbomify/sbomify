"""
Module for access request-related UI notifications
"""

from django.http import HttpRequest
from django.urls import reverse

from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.notifications.schemas import NotificationSchema
from sbomify.apps.teams.models import Team
from sbomify.logging import getLogger

logger = getLogger(__name__)


def get_notifications(request: HttpRequest) -> list[NotificationSchema]:
    """Get notifications for pending access requests.

    Returns notifications for owners/admins about pending access requests
    that need their attention.

    Args:
        request: The HTTP request object

    Returns:
        List of NotificationSchema objects, or empty list if no notifications
    """
    if not request.user.is_authenticated:
        return []

    notifications = []

    # Check if user has an active team in session
    if "current_team" not in request.session:
        return []

    try:
        team_key = request.session["current_team"]["key"]
        team = Team.objects.get(key=team_key)
    except (Team.DoesNotExist, KeyError, TypeError):
        return []

    # Only show notifications to owners and admins
    from sbomify.apps.teams.models import Member

    try:
        member = Member.objects.get(team=team, user=request.user)
        if member.role not in ("owner", "admin"):
            return []
    except Member.DoesNotExist:
        return []

    # Check for pending access requests
    company_nda = team.get_company_nda_document()
    requires_nda = company_nda is not None

    # Get pending requests query
    if requires_nda:
        # Only count requests that have NDA signature (request is complete)
        signed_request_ids = NDASignature.objects.values_list("access_request_id", flat=True)
        pending_requests = AccessRequest.objects.filter(
            team=team, status=AccessRequest.Status.PENDING, id__in=signed_request_ids
        )
    else:
        # Count all pending requests (no NDA required)
        pending_requests = AccessRequest.objects.filter(team=team, status=AccessRequest.Status.PENDING)

    pending_count = pending_requests.count()

    notification_id = f"access_request_pending_{team_key}"

    if pending_count > 0:
        # Get the oldest pending request to use its timestamp
        oldest_request = pending_requests.order_by("requested_at").first()

        # Use the actual request timestamp
        request_timestamp = oldest_request.requested_at.isoformat()

        # Create notification with link to trust center tab
        trust_center_url = reverse("teams:team_settings", kwargs={"team_key": team_key}) + "#trust-center"

        message = f"You have {pending_count} pending access request{'s' if pending_count > 1 else ''} to review."

        # Remove from dismissed list if there are pending requests
        dismissed_ids = set(request.session.get("dismissed_notifications", []))
        if notification_id in dismissed_ids:
            dismissed_ids.remove(notification_id)
            request.session["dismissed_notifications"] = list(dismissed_ids)
            request.session.save()

        notifications.append(
            NotificationSchema(
                id=notification_id,
                type="access_request_pending",
                message=message,
                severity="info",
                created_at=request_timestamp,
                action_url=trust_center_url,
            )
        )

    return notifications
