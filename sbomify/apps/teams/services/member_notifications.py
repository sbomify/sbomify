"""Notifications about membership changes that owners should know about."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from sbomify.apps.billing.billing_helpers import mask_email
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
        body = render_to_string("teams/emails/owner_invitation_notice.txt", context)
        html = render_to_string("teams/emails/owner_invitation_notice.html.j2", context)
    except Exception:
        logger.exception("Failed to render owner-invitation notice for team %s", team.key)
        return

    # One message per recipient, as everywhere else we mail members. A single
    # message addressed to every owner would put the full owner roster in the
    # To: header of each copy — and this is a security notice, so its recipient
    # list is exactly the thing not to broadcast. A failed send is logged and
    # the remaining owners are still notified; a failure here must never roll
    # back a successful invite.
    for recipient in recipients:
        try:
            email = EmailMultiAlternatives(
                subject=f"An owner-level invitation was created for {team.name}",
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
                reply_to=["hello@sbomify.com"],
            )
            email.attach_alternative(html, "text/html")
            email.send()
        except Exception:
            logger.exception(
                "Failed to notify %s of owner-level invitation for team %s", mask_email(recipient), team.key
            )
