"""
Module for billing-related email notifications
"""

import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

from teams.models import Member, Team
from sbomify.logging import getLogger

logger = getLogger(__name__)


def send_billing_email(subject, template_name, context, recipient_list):
    """Send a billing-related email using a template."""
    try:
        # Render email content from template
        html_message = render_to_string(f"billing/emails/{template_name}.html", context)
        plain_message = render_to_string(f"billing/emails/{template_name}.txt", context)

        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            html_message=html_message,
            fail_silently=False
        )
        logger.info(f"Sent {template_name} email to {recipient_list}")
    except Exception as e:
        logger.error(f"Failed to send {template_name} email: {str(e)}")
        raise


def notify_payment_past_due(team: Team, member: Member) -> None:
    """Notify team owner about past due payment."""
    send_billing_email(
        subject="Payment Past Due - Action Required",
        template_name="payment_past_due",
        context={},
        recipient_list=[member.user.email]
    )


def notify_payment_failed(team: Team, member: Member, invoice_id: str | None) -> None:
    """Notify team owner about failed payment."""
    subject = f"Payment failed for {team.name}"
    context = {
        "team_name": team.name,
        "billing_url": f"{settings.SITE_URL}/billing",
        "invoice_id": invoice_id
    }
    send_billing_email(
        subject=subject,
        template_name="payment_failed",
        context=context,
        recipient_list=[member.user.email]
    )


def notify_subscription_cancelled(team: Team, member: Member) -> None:
    """Notify team owner about subscription cancellation."""
    subject = f"Subscription cancelled for {team.name}"
    context = {
        "team_name": team.name,
        "billing_url": f"{settings.SITE_URL}/billing"
    }
    send_billing_email(
        subject=subject,
        template_name="subscription_cancelled",
        context=context,
        recipient_list=[member.user.email]
    )


def notify_payment_succeeded(team: Team, member: Member) -> None:
    """Notify team owner about successful payment."""
    subject = f"Payment successful for {team.name}"
    context = {
        "team_name": team.name,
        "billing_url": f"{settings.SITE_URL}/billing"
    }
    send_billing_email(
        subject=subject,
        template_name="payment_succeeded",
        context=context,
        recipient_list=[member.user.email]
    )


def notify_trial_ending(team: Team, member: Member, days_remaining: int) -> None:
    """Notify team owner that trial period is ending soon."""
    subject = f"Your {team.name} trial is ending in {days_remaining} days"
    context = {
        "team_name": team.name,
        "days_remaining": days_remaining,
        "trial_end_date": timezone.now() + timezone.timedelta(days=days_remaining),
        "upgrade_url": f"{settings.SITE_URL}/billing/upgrade"
    }
    send_billing_email(
        subject=subject,
        template_name="trial_ending",
        context=context,
        recipient_list=[member.user.email]
    )


def notify_trial_expired(team: Team, member: Member) -> None:
    """Notify team owner that trial period has expired."""
    subject = f"Your {team.name} trial has expired"
    context = {
        "team_name": team.name,
        "upgrade_url": f"{settings.SITE_URL}/billing/upgrade"
    }
    send_billing_email(
        subject=subject,
        template_name="trial_expired",
        context=context,
        recipient_list=[member.user.email]
    )


def notify_subscription_ended(team: Team, member: Member) -> None:
    """Notify team owner about subscription ending."""
    send_billing_email(
        subject="Subscription Ended",
        template_name="subscription_ended",
        context={},
        recipient_list=[member.user.email]
    )
