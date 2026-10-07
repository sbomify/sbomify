"""Inviting someone to a workspace, and taking an invitation back.

The members page and the API both come through here, so the seat count, the
duplicate rule and the email cannot drift between them.
"""

from __future__ import annotations

from typing import cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.template.loader import render_to_string

from sbomify.apps.core.authz import ROLE_GUEST
from sbomify.apps.core.models import User
from sbomify.apps.core.posthog_service import capture_for_request
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.url_utils import get_base_url
from sbomify.apps.teams.models import Invitation, Team
from sbomify.apps.teams.utils import user_seat

# Guests join through trust center access requests, never by invitation.
MEMBER_INVITE_ROLES = tuple(role for role, _label in settings.TEAMS_INVITABLE_ROLES if role != ROLE_GUEST)


def list_invitations(team: Team) -> ServiceResult[list[Invitation]]:
    """The workspace's invitations nobody has accepted yet, oldest first."""
    return ServiceResult.success(
        list(Invitation.objects.filter(team=team).select_related("team", "invited_by").order_by("created_at", "id"))
    )


def invite_member(request: HttpRequest, team: Team, email: str, role: str) -> ServiceResult[Invitation]:
    """Invite ``email`` to ``team`` as ``role`` and send the invitation.

    Fails with 400 for an address or role the members page would not take, 409
    while a live invitation exists, and 403 when the plan has no seat left.
    """
    email = email.strip()
    try:
        validate_email(email)
    except ValidationError:
        return ServiceResult.failure("Enter a valid email address", status_code=400)
    if role not in MEMBER_INVITE_ROLES:
        return ServiceResult.failure(f"Role must be one of: {', '.join(MEMBER_INVITE_ROLES)}", status_code=400)

    duplicate = f"Invitation already sent to {email}"
    existing = Invitation.objects.filter(team=team, email=email).first()
    if existing is not None:
        if not existing.has_expired:
            return ServiceResult.failure(duplicate, status_code=409)
        existing.delete()

    inviter = cast(User, request.user)
    # Counted and written under one lock, so another invitation cannot take the
    # last seat in between. The email is sent afterwards, on purpose: an SMTP
    # round trip has no business inside a row lock.
    try:
        with user_seat(team) as (seat_available, seat_error):
            if not seat_available:
                return ServiceResult.failure(seat_error, status_code=403)
            invitation = Invitation.objects.create(team=team, email=email, role=role, invited_by=inviter)
    except IntegrityError:
        # The same address invited twice at once: the duplicate check above
        # passed for both, and the unique (team, email) row lets one through.
        return ServiceResult.failure(duplicate, status_code=409)

    email_context = {
        "team": team,
        "invitation": invitation,
        "user": inviter,
        "base_url": get_base_url(),
    }
    message = EmailMultiAlternatives(
        subject=f"You're invited to join {team.name} on sbomify",
        body=render_to_string("teams/emails/team_invite_email.txt", email_context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
        reply_to=["hello@sbomify.com"],
    )
    message.attach_alternative(render_to_string("teams/emails/team_invite_email.html.j2", email_context), "text/html")
    message.send()

    # Capture AFTER message.send() — if SMTP fails (transient outage,
    # template render error) the request raises and we want the
    # funnel to reflect "no invite shipped", not an inflated
    # "invite_sent" count. Ship the email DOMAIN only — never the
    # local-part. The local-part identifies a person; the domain
    # identifies a B2B prospect / cohort which is the analytics
    # value here. A drive-by edit to ship the full email would
    # leak PII to PostHog. Domain alone can still be sensitive for
    # some B2B (e.g. an internal subsidiary) — acceptable trade-off
    # for the funnel metric.
    email_domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    team_key = team.key
    transaction.on_commit(
        lambda: capture_for_request(
            request,
            "team:member_invited",
            {"role": role, "invited_email_domain": email_domain},
            team_key=team_key,
        )
    )
    return ServiceResult.success(invitation)


def revoke_invitation(team: Team, invitation_id: int) -> ServiceResult[Invitation]:
    """Delete one of the workspace's invitations, so its link stops working."""
    invitation = Invitation.objects.filter(team=team, pk=invitation_id).first()
    if invitation is None:
        return ServiceResult.failure("Invitation not found", status_code=404)
    invitation.delete()
    return ServiceResult.success(invitation)
