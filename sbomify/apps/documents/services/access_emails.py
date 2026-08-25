"""Email notifications for trust-center access requests.

The API (``documents.access_apis``) and the HTMX views
(``documents.views.access_requests``) both drive the same four moments in an
access request's life, and until this module existed each carried its own copy
of the send code. The copies had already drifted: one selected admins with a
hardcoded ``("owner", "admin")`` while the other used the ``ADMINISTER`` tier,
so a role change would have been picked up by one entry point and not the
other. Both now call these functions.

Every function here swallows its own failures. A mailer outage must not roll
back an approval that has already been committed, and the caller has no
sensible recovery beyond what is logged.
"""

from __future__ import annotations

from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.url_utils import get_base_url
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.teams.models import Member, Team
from sbomify.logging import getLogger

logger = getLogger(__name__)

# Replies to a decision notice should reach a human at sbomify, not bounce off
# the unattended sender.
SUPPORT_REPLY_TO = "hello@sbomify.com"


def _send(
    *,
    subject: str,
    template: str,
    context: dict[str, object],
    to: str,
    reply_to: str = SUPPORT_REPLY_TO,
    failure_note: str,
) -> bool:
    """Render and send one message. Returns whether it went out."""
    if not to:
        logger.warning("%s: no recipient address", failure_note)
        return False
    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string(f"documents/emails/{template}.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to],
            reply_to=[reply_to],
        )
        email.attach_alternative(render_to_string(f"documents/emails/{template}.html.j2", context), "text/html")
        email.send()
        return True
    except Exception:
        logger.exception(failure_note)
        return False


def _requester_context(access_request: AccessRequest) -> dict[str, object]:
    return {
        "user": access_request.user,
        "team": access_request.team,
        "base_url": get_base_url(),
    }


def notify_admins_of_access_request(access_request: AccessRequest, team: Team, requires_nda: bool = False) -> None:
    """Tell every owner and admin that someone has asked for access."""
    try:
        admin_members = Member.objects.filter(team=team, role__in=ADMINISTER).select_related("user")
        if not admin_members.exists():
            logger.warning("No admins found for team %s to notify about access request %s", team.key, access_request.id)
            return

        requester_name = (
            f"{access_request.user.first_name} {access_request.user.last_name}".strip() or access_request.user.username
        )
        requester_email = access_request.user.email
        review_url = reverse("documents:access_request_queue", kwargs={"team_key": team.key})
        nda_signed = NDASignature.objects.live().filter(access_request=access_request).exists()

        context = {
            "team": team,
            "requester_name": requester_name,
            "requester_email": requester_email,
            "requested_at": access_request.requested_at.strftime("%B %d, %Y at %I:%M %p"),
            "requires_nda": requires_nda,
            "nda_signed": nda_signed,
            "review_link": f"{get_base_url()}{review_url}",
            "base_url": get_base_url(),
        }

        for admin_member in admin_members:
            _send(
                subject=f"New access request for {team.name}",
                template="access_request_notification",
                context={**context, "admin_user": admin_member.user},
                to=admin_member.user.email,
                # Reply-to the requester so an admin's reply reaches them, not our own inbox.
                reply_to=requester_email or SUPPORT_REPLY_TO,
                failure_note=f"Failed to send access request notification for request {access_request.id}",
            )
    except Exception:
        logger.exception("Error notifying admins of access request %s", access_request.id)


def notify_access_approved(access_request: AccessRequest) -> None:
    """Tell the requester they are in, with a link that lands them logged in."""
    login_url = reverse("core:keycloak_login")
    redirect_url = reverse("core:workspace_public", kwargs={"workspace_key": access_request.team.key})
    context = _requester_context(access_request)
    context["login_link"] = f"{get_base_url()}{login_url}?next={quote(redirect_url)}"

    _send(
        subject=f"Access approved for {access_request.team.name}",
        template="access_approved",
        context=context,
        to=access_request.user.email,
        failure_note=f"Failed to send access approval email for request {access_request.id}",
    )


def notify_access_rejected(access_request: AccessRequest) -> None:
    """Tell the requester the request was not granted."""
    _send(
        subject=f"Access request update for {access_request.team.name}",
        template="access_rejected",
        context=_requester_context(access_request),
        to=access_request.user.email,
        failure_note=f"Failed to send access rejection email for request {access_request.id}",
    )


def notify_access_revoked(access_request: AccessRequest) -> None:
    """Tell the requester their access has been withdrawn."""
    _send(
        subject=f"Access update for {access_request.team.name}",
        template="access_revoked",
        context=_requester_context(access_request),
        to=access_request.user.email,
        failure_note=f"Failed to send access revocation email for request {access_request.id}",
    )
