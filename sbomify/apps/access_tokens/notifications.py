"""Bell notifications for access tokens nearing expiry.

Pull-based like every provider in NOTIFICATION_PROVIDERS: computed per
request from ``expires_at``, so there is no state to keep in step and the
session's dismissal mechanism applies unchanged. The companion daily email
task lives in :mod:`.tasks`.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.notifications.schemas import NotificationSchema
from sbomify.logging import getLogger

logger = getLogger(__name__)

WARNING_WINDOW_DAYS = 14


def days_until(expires_at: datetime, now: datetime) -> int:
    """Whole days remaining, counted the way a person does.

    Ceiling rather than floor: a token expiring in 4 days 23 hours reads
    "in 5 days", and anything inside the final 24 hours reads "tomorrow".
    """
    return max(0, math.ceil((expires_at - now).total_seconds() / 86400))


def get_notifications(request: HttpRequest) -> list[NotificationSchema]:
    """Warnings for the user's own expiring tokens, plus the current
    workspace's bot tokens when the user can act on them (owner/admin) —
    a bot's 401s otherwise surface only as unexplained CI failures."""
    if not request.user.is_authenticated:
        return []

    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.teams.models import Member

    now = timezone.now()
    cutoff = now + timedelta(days=WARNING_WINDOW_DAYS)

    tokens = list(
        AccessToken.objects.filter(user=request.user, expires_at__gt=now, expires_at__lte=cutoff).select_related("team")
    )

    team_key = (request.session.get("current_team") or {}).get("key")
    if team_key and (request.session.get("current_team") or {}).get("role") in ("owner", "admin"):
        bot_user_ids = Member.objects.filter(team__key=team_key, role="bot").values_list("user_id", flat=True)
        tokens.extend(
            AccessToken.objects.filter(
                user_id__in=bot_user_ids, team__key=team_key, expires_at__gt=now, expires_at__lte=cutoff
            ).select_related("team")
        )

    notifications = []
    for token in tokens:
        if token.expires_at is None:
            continue
        days = days_until(token.expires_at, now)
        when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
        action_url = None
        if token.team is not None:
            action_url = reverse("teams:team_settings", kwargs={"team_key": token.team.key}) + "#tokens"
        notifications.append(
            NotificationSchema(
                # Day-resolution id: dismissing today's warning keeps it away
                # until the remaining time changes, then it returns.
                id=f"token_expiry_{token.id}_{days}",
                type="token_expiry",
                message=f'Access token "{token.description}" expires {when}.',
                action_url=action_url,
                severity="error" if days <= 1 else "warning",
                created_at=now.isoformat(),
            )
        )
    return notifications
