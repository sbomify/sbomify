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
        subject,
        text_message,
        settings.DEFAULT_FROM_EMAIL,
        [owner.member.user.email],
        html_message=html_message,
        fail_silently=True,
    )


def notify_payment_past_due(team: Team, owner: Member) -> None:
    """Send payment past due notification"""
    send_billing_email(
        team,
        owner,
        "[sbomify] Payment Past Due - Action Required",
        "payment_past_due",
        {},
    )


def notify_payment_failed(team: Team, owner: Member, attempt_count: int, next_payment_attempt: str) -> None:
    """Send payment failed notification"""
    send_billing_email(
        team,
        owner,
        "[sbomify] Payment Failed - Action Required",
        "payment_failed",
        {
            "attempt_count": attempt_count,
            "next_payment_attempt": next_payment_attempt,
        },
    )


def notify_subscription_cancelled(team: Team, owner: Member) -> None:
    """Send subscription cancelled notification"""
    send_billing_email(
        team,
        owner,
        "[sbomify] Subscription Cancelled",
        "subscription_cancelled",
        {},
    )


def notify_payment_succeeded(team: Team, owner: Member) -> None:
    """Send payment succeeded notification"""
    send_billing_email(
        team,
        owner,
        "[sbomify] Payment Successful",
        "payment_succeeded",
        {},
    )
