"""Notifications about membership changes that owners should know about."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from sbomify.apps.core.authz import OWNER_ONLY
from sbomify.apps.core.models import User
from sbomify.apps.core.url_utils import get_base_url
from sbomify.apps.teams.models import Member
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

logger = getLogger(__name__)


def notify_owners_of_owner_invitation(team: Team, actor: User, invited_email: str) -> None:
    """Tell existing owners that a non-owner invited someone at owner level.

    Admins may invite at any level, which means the "admins cannot remove an
    owner" rule is bypassable in principle: an admin could invite an owner they
    control and act through it. We allow it deliberately — admins are trusted,
    and the rule exists to prevent accidents rather than to defend against a
    malicious admin — so the mitigation is visibility, not prohibition.

    Never raises: a failed notification must not roll back a successful invite.
    """
    recipients = [
        member.user.email
        for member in Member.objects.filter(team=team, role__in=OWNER_ONLY).select_related("user")
        if member.user.email and member.user_id != actor.pk
    ]
    if not recipients:
        return

    context = {
        "team": team,
        "actor": actor,
        "invited_email": invited_email,
        "base_url": get_base_url(),
    }

    try:
        email = EmailMultiAlternatives(
            subject=f"An owner-level invitation was created for {team.name}",
            body=render_to_string("teams/emails/owner_invitation_notice.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
            reply_to=["hello@sbomify.com"],
        )
        email.attach_alternative(render_to_string("teams/emails/owner_invitation_notice.html.j2", context), "text/html")
        email.send()
    except Exception:
        logger.exception("Failed to notify owners of owner-level invitation for team %s", team.key)
