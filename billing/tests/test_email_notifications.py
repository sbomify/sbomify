"""Tests for billing email notifications."""

from unittest.mock import patch

import pytest
from django.core import mail
from django.urls import reverse

from billing import email_notifications
from teams.models import Member, Team, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(db):
    """Create a test team."""
    user = User.objects.create_user(
        email="test@example.com",
        password="testpass123",
        first_name="Test",
        last_name="User",
    )
    team = Team.objects.create(
        name="Test Team",
        key="test-team",
        billing_plan="business",
        billing_plan_limits={
            "max_products": 10,
            "max_projects": 20,
            "max_components": 100,
            "stripe_customer_id": "cus_test123",
            "stripe_subscription_id": "sub_test123",
            "subscription_status": "active",
            "last_updated": "2024-01-01T00:00:00Z",
        },
    )
    member = Member.objects.create(
        team=team,
        user=user,
        role="owner",
    )
    return team, member


def test_notify_trial_ending(team):
    """Test trial ending notification."""
    team, member = team
    days_remaining = 3

    with patch("django.core.mail.send_mail") as mock_send_mail:
        email_notifications.notify_trial_ending(team, member, days_remaining)
        mock_send_mail.assert_called_once()

        # Verify email content
        call_args = mock_send_mail.call_args[0]
        assert f"Your {team.name} trial is ending in {days_remaining} days" in call_args[0]
        assert team.name in call_args[1]
        assert str(days_remaining) in call_args[1]
        assert reverse("billing:select_plan", kwargs={"team_key": team.key}) in call_args[1]


def test_notify_payment_failed(team):
    """Test payment failed notification."""
    team, member = team
    invoice_id = "in_test123"

    with patch("django.core.mail.send_mail") as mock_send_mail:
        email_notifications.notify_payment_failed(team, member, invoice_id)
        mock_send_mail.assert_called_once()

        # Verify email content
        call_args = mock_send_mail.call_args[0]
        assert f"Payment failed for {team.name}" in call_args[0]
        assert team.name in call_args[1]
        assert invoice_id in call_args[1]
        assert reverse("billing:select_plan", kwargs={"team_key": team.key}) in call_args[1]


def test_notify_payment_failed_no_invoice(team):
    """Test payment failed notification without invoice ID."""
    team, member = team

    with patch("django.core.mail.send_mail") as mock_send_mail:
        email_notifications.notify_payment_failed(team, member, None)
        mock_send_mail.assert_called_once()

        # Verify email content
        call_args = mock_send_mail.call_args[0]
        assert f"Payment failed for {team.name}" in call_args[0]
        assert team.name in call_args[1]
        assert "Invoice ID" not in call_args[1]
        assert reverse("billing:select_plan", kwargs={"team_key": team.key}) in call_args[1]


def test_notify_payment_past_due(team):
    """Test payment past due notification."""
    team, member = team

    with patch("billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_payment_past_due(team, member)
        mock_send.assert_called_once_with(
            team,
            member,
            "[sbomify] Payment Past Due - Action Required",
            "payment_past_due",
            {},
        )


def test_notify_subscription_cancelled(team):
    """Test subscription cancelled notification."""
    team, member = team

    with patch("billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_subscription_cancelled(team, member)
        mock_send.assert_called_once_with(
            team,
            member,
            "[sbomify] Subscription Cancelled",
            "subscription_cancelled",
            {},
        )


def test_notify_payment_succeeded(team):
    """Test payment succeeded notification."""
    team, member = team

    with patch("billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_payment_succeeded(team, member)
        mock_send.assert_called_once_with(
            team,
            member,
            "[sbomify] Payment Successful",
            "payment_succeeded",
            {},
        )


def test_send_billing_email(team):
    """Test sending billing email with template."""
    team, member = team
    subject = "Test Subject"
    template = "test_template"
    context = {"test_key": "test_value"}

    with patch("django.template.loader.render_to_string") as mock_render:
        mock_render.side_effect = ["html_content", "text_content"]
        with patch("django.core.mail.send_mail") as mock_send:
            email_notifications.send_billing_email(team, member, subject, template, context)
            mock_send.assert_called_once_with(
                subject,
                "text_content",
                None,  # DEFAULT_FROM_EMAIL
                [member.member.user.email],
                html_message="html_content",
                fail_silently=True,
            )