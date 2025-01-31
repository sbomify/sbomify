from ninja import Router
from ninja.security import django_auth

from access_tokens.auth import PersonalAccessTokenAuth
from core.schemas import ErrorResponse

from .schemas import NotificationSchema
from .utils import get_notifications

router = Router(tags=["notifications"], auth=(PersonalAccessTokenAuth(), django_auth))


@router.get(
    "/",
    response={200: list[NotificationSchema], 403: ErrorResponse},
)
def list_notifications(request):
    """Get all active notifications for the current user"""
    return get_notifications(request)