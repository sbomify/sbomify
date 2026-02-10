"""
Module for billing-related email notifications
"""

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

from sbomify.apps.core.url_utils import get_base_url
from sbomify.apps.teams.models import Member, Team
from sbomify.logging import getLogger

logger = getLogger(__name__)


def _get_billing_portal_url(team: Team) -> str:
    """Get the Stripe billing portal URL for a team (for managing payment methods)."""
    base_url = get_base_url()
    path = reverse("billing:create_portal_session", kwargs={"team_key": team.key})
    return f"{base_url}{path}"


def _get_select_plan_url(team: Team) -> str:
    """Get the plan selection URL for a team (for upgrading)."""
    base_url = get_base_url()
    path = reverse("billing:select_plan", kwargs={"team_key": team.key})
    return f"{base_url}{path}"


def _get_base_context(team: Team, member: Member) -> dict:
    """Get base context for all billing emails."""
    user = member.user
    user_name = user.get_full_name() or user.email
    base_url = get_base_url()
    return {
        "user_name": user_name,
        "team_name": team.name,
        "team": team,
        "base_url": base_url,
        "action_url": _get_billing_portal_url(team),
        "upgrade_url": _get_select_plan_url(team),
    }


def send_billing_email(team: Team, member: Member, subject: str, template_name: str, extra_context: dict) -> None:
    """Send a billing-related email using a template."""
    if not team:
        logger.error("Cannot send billing email: team is None")
        return

    if not member:
        logger.error("Cannot send billing email: member is None")
        return

    try:
        # Build context with base + extra
        context = _get_base_context(team, member)
        context.update(extra_context)

        # Render email content from template
        try:
            html_message = render_to_string(f"billing/emails/{template_name}.html.j2", context)
            plain_message = render_to_string(f"billing/emails/{template_name}.txt", context)
        except Exception as e:
            logger.error(f"Failed to render email template {template_name}: {e}")
            return

        # Send email
        try:
            send_mail(
                subject,
                plain_message,
                None,  # Use default from_email
                [member.user.email],
                html_message=html_message,
                fail_silently=True,
            )
            logger.info(f"Sent {template_name} email to {member.user.email}")
        except Exception as e:
            logger.error(f"Failed to send {template_name} email: {e}")
            return
    except Exception as e:
        logger.error(f"Failed to send {template_name} email: {e}")
        return


def notify_payment_past_due(team: Team, member: Member) -> None:
    """Notify team owner about past due payment."""
    subject = f"Payment past due for {team.name}"
    send_billing_email(team, member, subject, "payment_past_due", {})


def notify_payment_failed(team: Team, member: Member, invoice_id: str | None) -> None:
    """Notify team owner about failed payment."""
    subject = f"Payment failed for {team.name}"
    send_billing_email(team, member, subject, "payment_failed", {"invoice_id": invoice_id})


def notify_subscription_cancelled(team: Team, member: Member) -> None:
    """Notify team owner about subscription cancellation."""
    subject = "Your sbomify subscription has been cancelled"
    send_billing_email(team, member, subject, "subscription_cancelled", {})


def notify_payment_succeeded(team: Team, member: Member) -> None:
    """Notify team owner about successful payment."""
    subject = f"Payment received for {team.name}"
    send_billing_email(team, member, subject, "payment_succeeded", {})


def notify_trial_ending(team: Team, member: Member, days_remaining: int) -> None:
    """Notify team owner that trial period is ending soon."""
    subject = f"Your sbomify trial ends in {days_remaining} days"
    send_billing_email(team, member, subject, "trial_ending", {"days_remaining": days_remaining})


def notify_trial_expired(team: Team, member: Member) -> None:
    """Notify team owner that trial period has expired."""
    subject = "Your sbomify trial has expired"
    send_billing_email(team, member, subject, "trial_expired", {})


def notify_subscription_ended(team: Team, member: Member) -> None:
    """Notify team owner about subscription ending."""
    subject = "Your sbomify subscription has ended"
    send_billing_email(team, member, subject, "subscription_ended", {})
