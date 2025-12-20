from ninja import Router
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.schemas import ErrorResponse

from .schemas import NotificationSchema
from .utils import get_notifications

router = Router(tags=["Notifications"], auth=(PersonalAccessTokenAuth(), django_auth))


@router.get(
    "/",
    response={200: list[NotificationSchema], 403: ErrorResponse},
)
def list_notifications(request):
    """Get all active notifications for the current user and their active team"""
    return get_notifications(request)


@router.post(
    "/clear/",
    response={200: dict, 403: ErrorResponse},
)
def clear_notifications(request):
    """Clear all dismissible notifications (excluding upgrade notifications)"""
    # Get current notifications to get their IDs
    current_notifications = get_notifications(request)

    # Get dismissed IDs from session
    dismissed_ids = set(request.session.get("dismissed_notifications", []))

    # Add all non-upgrade notification IDs to dismissed list
    for notification in current_notifications:
        # Don't allow dismissing upgrade notifications
        if notification.type != "community_upgrade":
            dismissed_ids.add(notification.id)

    # Save dismissed IDs to session
    request.session["dismissed_notifications"] = list(dismissed_ids)
    request.session.save()

    return {"status": "success", "message": "Notifications cleared"}
