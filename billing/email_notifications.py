"""
Module for billing-related email notifications
"""

import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string

from teams.models import Member, Team

logger = logging.getLogger(__name__)


def send_billing_email(team: Team, member: Member, subject: str, template: str, context: dict) -> None:
    """Send a billing-related email using a template."""
    if not team or not member:
        logger.error(f"Failed to send {template} email: Invalid team or member")
        return

    try:
        html_message = render_to_string(f"billing/emails/{template}.html", context)
        text_message = render_to_string(f"billing/emails/{template}.txt", context)

        send_mail(
            subject,
            text_message,
            None,  # DEFAULT_FROM_EMAIL
            [member.user.email],
            html_message=html_message,
            fail_silently=True,
        )
        logger.info(f"Sent {template} email to {member.user.email}")
    except Exception as e:
        logger.error(f"Failed to send {template} email to {member.user.email}: {str(e)}")


def notify_payment_past_due(team: Team, member: Member) -> None:
    """Notify team owner about past due payment."""
    send_billing_email(
        team,
        member,
        "Payment Past Due - Action Required",
        "payment_past_due",
        {},
    )


def notify_payment_failed(team: Team, member: Member, invoice_id: str | None) -> None:
    """Notify team owner about failed payment."""
    send_billing_email(
        team,
        member,
        "Payment Failed",
        "payment_failed",
        {"invoice_id": invoice_id},
    )


def notify_subscription_cancelled(team: Team, member: Member) -> None:
    """Notify team owner about subscription cancellation."""
    send_billing_email(
        team,
        member,
        "Subscription Cancelled",
        "subscription_cancelled",
        {},
    )


def notify_payment_succeeded(team: Team, member: Member) -> None:
    """Notify team owner about successful payment."""
    send_billing_email(
        team,
        member,
        "Payment Successful",
        "payment_succeeded",
        {},
    )


def notify_trial_ending(team: Team, member: Member, days_remaining: int) -> None:
    """Notify team owner that trial period is ending."""
    send_billing_email(
        team,
        member,
        "Trial Period Ending",
        "trial_ending",
        {"days_remaining": days_remaining},
    )


def notify_subscription_ended(team: Team, member: Member) -> None:
    """Notify team owner about subscription ending."""
    send_billing_email(
        team,
        member,
        "Subscription Ended",
        "subscription_ended",
        {},
    )
