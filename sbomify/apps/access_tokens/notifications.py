"""Bell notifications for access tokens nearing expiry.

Pull-based like every provider in NOTIFICATION_PROVIDERS: computed per
request from ``expires_at``, so there is no state to keep in step and the
session's dismissal mechanism applies unchanged. The companion daily email
task lives in :mod:`.tasks`.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.notifications.schemas import NotificationSchema
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.access_tokens.models import AccessToken

logger = getLogger(__name__)

WARNING_WINDOW_DAYS = 14


def days_until(expires_at: datetime, now: datetime) -> int:
    """Whole days remaining, counted the way a person does.

    Ceiling rather than floor: a token expiring in 4 days 23 hours reads
    "in 5 days", and anything inside the final 24 hours reads "tomorrow".
    """
    return max(0, math.ceil((expires_at - now).total_seconds() / 86400))


def lifetime_days(token: "AccessToken") -> int | None:
    """How long the token was issued for, or None when that is unknowable."""
    if token.expires_at is None or token.created_at is None:
        return None
    return max(0, math.ceil((token.expires_at - token.created_at).total_seconds() / 86400))


def is_short_lived(token: "AccessToken") -> bool:
    """True when the token's whole life fits inside the warning window.

    Such a token is inside the window from the moment it exists, so a warning
    reports back a lifetime the reader just chose rather than telling them
    anything. The CI/CD dialog issues 7-day tokens, which is well inside the
    14-day window.
    """
    lifetime = lifetime_days(token)
    return lifetime is not None and lifetime <= WARNING_WINDOW_DAYS


def get_notifications(request: HttpRequest) -> list[NotificationSchema]:
    """Warnings for the user's own expiring tokens, plus the current
    workspace's bot tokens when the user can act on them (owner/admin) —
    a bot's 401s otherwise surface only as unexplained CI failures."""
    if not request.user.is_authenticated:
        return []

    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.core.authz import ADMINISTER
    from sbomify.apps.teams.models import Member
    from sbomify.apps.teams.queries import get_member_role_by_key

    now = timezone.now()
    cutoff = now + timedelta(days=WARNING_WINDOW_DAYS)

    tokens = list(
        AccessToken.objects.filter(user=request.user, expires_at__gt=now, expires_at__lte=cutoff).select_related("team")
    )

    # Live Member row and the tier, not the session cache and a role literal:
    # this decides whether someone is shown the workspace's bot tokens, so a
    # demoted admin would keep seeing them until the 300s cache turned over.
    team_key = (request.session.get("current_team") or {}).get("key")
    if team_key and get_member_role_by_key(request.user, team_key) in ADMINISTER:
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
        lifetime = lifetime_days(token)
        # A token that lives under a day is born inside its final day, so the
        # final-day carve-out below would keep it on the bell for its whole
        # life. The OIDC publish exchange mints a 15-minute token per CI run,
        # which piled up one "expires tomorrow" badge per publish. Expiring
        # that soon is the token's design, not an event.
        if lifetime is not None and lifetime <= 1:
            continue
        # Keep the final day for short-lived tokens: silence for the whole life
        # would let a pipeline start failing with no notice at all.
        if days > 1 and is_short_lived(token):
            continue
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
