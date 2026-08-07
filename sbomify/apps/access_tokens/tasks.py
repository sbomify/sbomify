"""Daily email warnings for access tokens nearing expiry.

A PAT lapsing shows up as unexplained CI 401s, so the warning has to reach an
inbox before that. Thresholds are 14, 7 and 1 days; each is sent once per
token (:class:`~.models.TokenExpiryWarning`), and crossing is tested with <=
so a missed cron day delays a warning rather than skipping it. A token
already inside several thresholds gets one email — the tightest — with the
wider ones marked sent so they cannot trail in later.

Bot tokens have no human inbox behind them, so their warnings go to the
workspace's owners instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import dramatiq
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from dramatiq_crontab import cron

from sbomify.apps.core.url_utils import get_base_url
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.access_tokens.models import AccessToken

logger = getLogger(__name__)

EXPIRY_WARNING_THRESHOLDS = (14, 7, 1)


def _recipients(token: "AccessToken") -> list[str]:
    """The token creator's inbox, or the workspace owners' for a bot's token."""
    from sbomify.apps.teams.models import Member

    if token.team_id and Member.objects.filter(user_id=token.user_id, team_id=token.team_id, role="bot").exists():
        return [
            email
            for email in Member.objects.filter(team_id=token.team_id, role="owner").values_list(
                "user__email", flat=True
            )
            if email
        ]
    return [token.user.email] if token.user.email else []


@cron("0 6 * * *")  # type: ignore[untyped-decorator]  # Daily, before working hours
@dramatiq.actor(queue_name="token_expiry", max_retries=1, time_limit=300000)
def warn_expiring_tokens() -> int:
    """Send the due expiry warnings. Returns how many emails went out."""
    from datetime import timedelta

    from sbomify.apps.access_tokens.models import AccessToken, TokenExpiryWarning

    now = timezone.now()
    widest = max(EXPIRY_WARNING_THRESHOLDS)
    tokens = (
        AccessToken.objects.filter(expires_at__gt=now, expires_at__lte=now + timedelta(days=widest))
        .select_related("user", "team")
        .prefetch_related("expiry_warnings")
    )

    sent = 0
    for token in tokens:
        if token.expires_at is None:
            continue
        from sbomify.apps.access_tokens.notifications import lifetime_days

        already = {warning.threshold_days for warning in token.expiry_warnings.all()}
        # A threshold that reaches at least as far as the token's whole life
        # was already true the moment it was issued, so crossing it is not
        # news. The equal case is the one that matters: a 7-day CI token sits
        # exactly on the 7-day threshold at creation, and would otherwise be
        # mailed about on the first sweep after it was made.
        lifetime = lifetime_days(token)
        thresholds = [t for t in EXPIRY_WARNING_THRESHOLDS if lifetime is None or t < lifetime]
        due = [t for t in thresholds if token.expires_at <= now + timedelta(days=t)]
        unsent = [t for t in due if t not in already]
        if not unsent:
            continue

        recipients = _recipients(token)
        if not recipients:
            # No threshold is marked here. Marking one would record a warning
            # that nobody received, and the token would then pass its expiry in
            # silence even if an address were added the next day.
            logger.warning(f"Token {token.id} nears expiry but has no reachable recipient")
            continue

        from sbomify.apps.access_tokens.notifications import days_until

        days_left = days_until(token.expires_at, now)
        context = {
            "token": token,
            "days_left": days_left,
            "expires_on": token.expires_at,
            "team": token.team,
            # get_base_url rather than the raw setting: it guarantees a scheme,
            # and a schemeless APP_BASE_URL would otherwise put a relative link
            # in an email, where there is no page for it to be relative to.
            "base_url": get_base_url(),
        }
        email = EmailMultiAlternatives(
            subject=f'Access token "{token.description}" expires in {days_left} day{"" if days_left == 1 else "s"}',
            body=render_to_string("access_tokens/emails/token_expiry_email.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        email.attach_alternative(
            render_to_string("access_tokens/emails/token_expiry_email.html.j2", context), "text/html"
        )
        try:
            email.send()
            sent += 1
        except Exception:
            logger.exception(f"Could not send expiry warning for token {token.id}")
            continue

        # Mark every due threshold, not only the tightest: once the 7-day
        # warning went out, a trailing 14-day one would read as noise.
        TokenExpiryWarning.objects.bulk_create(
            [TokenExpiryWarning(token=token, threshold_days=t) for t in unsent],
            ignore_conflicts=True,
        )
    return sent
