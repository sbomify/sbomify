"""
Module for billing-related email notifications
"""

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

from sbomify.logging import getLogger
from teams.models import Member, Team

logger = getLogger(__name__)


def send_billing_email(team: Team, owner: Member, subject: str, template: str, context: dict) -> None:
    """Send billing-related email notification using HTML template"""
    try:
        context.update(
            {
                "team_name": team.name,
                "user_name": owner.member.user.get_full_name() or owner.member.user.email,
                "action_url": f"{settings.WEBSITE_BASE_URL}{reverse('billing:select_plan', kwargs={'team_key': team.key})}",
            }
        )

        html_message = render_to_string(f"billing/emails/{template}.html", context)
        text_message = render_to_string(f"billing/emails/{template}.txt", context)

        send_mail(
            f"{settings.EMAIL_SUBJECT_PREFIX}{subject}",
            text_message,
            settings.DEFAULT_FROM_EMAIL,
            [owner.member.user.email],
            html_message=html_message,
            fail_silently=True,
        )
        logger.info(f"Sent {template} email to {owner.member.user.email}")
    except Exception as e:
        logger.exception(f"Error sending {template} email: {str(e)}")


def notify_payment_past_due(team: Team, owner: Member) -> None:
    """Send payment past due notification"""
    send_billing_email(
        team,
        owner,
        "Payment Past Due - Action Required",
        "payment_past_due",
        {},
    )


def notify_payment_failed(team: Team, owner: Member, invoice_id: str | None) -> None:
    """Send notification about failed payment."""
    subject = f"Payment failed for {team.name}"
    message = f"""
    We were unable to process your payment for {team.name}.

    {f'Invoice ID: {invoice_id}' if invoice_id else ''}

    Please update your payment information to continue using all features:
    {reverse('billing:select_plan', kwargs={'team_key': team.key})}

    If you have any questions, please don't hesitate to contact us.
    """

    send_mail(
        f"{settings.EMAIL_SUBJECT_PREFIX}{subject}",
        message,
        settings.DEFAULT_FROM_EMAIL,
        [owner.member.user.email],
        fail_silently=True,
    )
    logger.info(f"Sent payment failed notification to {owner.member.user.email}")


def notify_subscription_cancelled(team: Team, owner: Member) -> None:
    """Send subscription cancelled notification"""
    send_billing_email(
        team,
        owner,
        "Subscription Cancelled",
        "subscription_cancelled",
        {},
    )


def notify_payment_succeeded(team: Team, owner: Member) -> None:
    """Send payment succeeded notification"""
    send_billing_email(
        team,
        owner,
        "Payment Successful",
        "payment_succeeded",
        {},
    )


def notify_trial_ending(team: Team, owner: Member, days_remaining: int) -> None:
    """Send notification about trial ending soon."""
    subject = f"Your {team.name} trial is ending in {days_remaining} days"
    message = f"""
    Your trial for {team.name} will end in {days_remaining} days.

    To continue using all features, please add your payment information:
    {reverse('billing:select_plan', kwargs={'team_key': team.key})}

    If you have any questions, please don't hesitate to contact us.
    """

    send_mail(
        f"{settings.EMAIL_SUBJECT_PREFIX}{subject}",
        message,
        settings.DEFAULT_FROM_EMAIL,
        [owner.member.user.email],
        fail_silently=True,
    )
    logger.info(f"Sent trial ending notification to {owner.member.user.email}")
