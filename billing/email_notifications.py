"""
Module for billing-related email notifications
"""

from django.core.mail import send_mail
from django.template.loader import render_to_string

from sbomify.logging import getLogger
from teams.models import Member, Team

logger = getLogger(__name__)


def send_billing_email(team: Team, member: Member, subject: str, template_name: str, context: dict) -> None:
    """Send a billing-related email using a template."""
    if not team:
        logger.error("Cannot send billing email: team is None")
        return

    if not member:
        logger.error("Cannot send billing email: member is None")
        return

    try:
        # Render email content from template
        try:
            html_message = render_to_string(f"billing/emails/{template_name}.html", context)
            plain_message = render_to_string(f"billing/emails/{template_name}.txt", context)
        except Exception as e:
            logger.error(f"Failed to render email template {template_name}: {str(e)}")
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
            logger.error(f"Failed to send {template_name} email: {str(e)}")
            return
    except Exception as e:
        logger.error(f"Failed to send {template_name} email: {str(e)}")
        return


def notify_payment_past_due(team: Team, member: Member) -> None:
    """Notify team owner about past due payment."""
    send_billing_email(team, member, "Payment Past Due - Action Required", "payment_past_due", {})


def notify_payment_failed(team: Team, member: Member, invoice_id: str | None) -> None:
    """Notify team owner about failed payment."""
    send_billing_email(team, member, "Payment Failed", "payment_failed", {"invoice_id": invoice_id})


def notify_subscription_cancelled(team: Team, member: Member) -> None:
    """Notify team owner about subscription cancellation."""
    send_billing_email(team, member, "Subscription Cancelled", "subscription_cancelled", {})


def notify_payment_succeeded(team: Team, member: Member) -> None:
    """Notify team owner about successful payment."""
    send_billing_email(team, member, "Payment Successful", "payment_succeeded", {})


def notify_trial_ending(team: Team, member: Member, days_remaining: int) -> None:
    """Notify team owner that trial period is ending soon."""
    send_billing_email(team, member, "Trial Period Ending", "trial_ending", {"days_remaining": days_remaining})


def notify_trial_expired(team: Team, member: Member) -> None:
    """Notify team owner that trial period has expired."""
    send_billing_email(team, member, "Trial Expired", "trial_expired", {})


def notify_subscription_ended(team: Team, member: Member) -> None:
    """Notify team owner about subscription ending."""
    send_billing_email(team, member, "Subscription Ended", "subscription_ended", {})
