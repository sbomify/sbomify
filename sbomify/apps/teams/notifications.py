"""
Notification provider for pending workspace invitations.

Surfaces incoming invitations in the notification center (bell icon)
so users are aware of pending invitations without needing to visit settings.
"""

from django.http import HttpRequest
from django.urls import reverse

from sbomify.apps.notifications.schemas import NotificationSchema
from sbomify.apps.teams.queries import get_pending_invitations_for_email
from sbomify.logging import getLogger

logger = getLogger(__name__)


def get_notifications(request: HttpRequest) -> list[NotificationSchema]:
    """Return a notification for each pending workspace invitation."""
    if not request.user.is_authenticated:
        return []

    email = request.user.email
    if not email:
        return []

    try:
        pending = get_pending_invitations_for_email(email)

        # Accepting happens on the user's own settings page. Pointing at the
        # current workspace's members tab sent someone invited to workspace B
        # to workspace A's member list, which holds no invitation of theirs.
        action_url = reverse("core:settings")

        notifications: list[NotificationSchema] = []
        for inv in pending:
            notifications.append(
                NotificationSchema(
                    id=f"pending_invitation_{inv.id}",
                    type="pending_invitation",
                    message=f"You've been invited to join {inv.team.display_name} as {inv.role}.",
                    severity="info",
                    created_at=inv.created_at.isoformat(),
                    action_url=action_url,
                )
            )

        return notifications
    except Exception:
        logger.exception("Error checking pending invitation notifications")
        return []
