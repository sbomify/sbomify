"""Tests for billing email notifications."""

from unittest.mock import patch
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from billing import email_notifications
from teams.models import Member, Team

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def team(db):
    """Create a test team with a member."""
    team = Team.objects.create(name="Test Team", key="test-team")
    user = User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123"
    )
    member = Member.objects.create(
        team=team,
        user=user,
        role="owner"
    )
    return team, member


def test_notify_trial_ending(team):
    """Test trial ending notification."""
    team, member = team
    days_remaining = 3

    with patch("billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_trial_ending(team, member, days_remaining)
        mock_send.assert_called_once_with(
            team,
            member,
            "Trial Period Ending",
            "trial_ending",
            {"days_remaining": days_remaining},
        )


def test_notify_payment_failed(team):
    """Test payment failed notification."""
    team, member = team
    invoice_id = "inv_123"

    with patch("billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_payment_failed(team, member, invoice_id)
        mock_send.assert_called_once_with(
            team,
            member,
            "Payment Failed",
            "payment_failed",
            {"invoice_id": invoice_id},
        )


def test_notify_payment_failed_no_invoice(team):
    """Test payment failed notification without invoice ID."""
    team, member = team

    with patch("billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_payment_failed(team, member, None)
        mock_send.assert_called_once_with(
            team,
            member,
            "Payment Failed",
            "payment_failed",
            {"invoice_id": None},
        )


def test_notify_payment_past_due(team):
    """Test payment past due notification."""
    team, member = team

    with patch("billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_payment_past_due(team, member)
        mock_send.assert_called_once_with(
            team,
            member,
            "Payment Past Due - Action Required",
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
            "Subscription Cancelled",
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
            "Payment Successful",
            "payment_succeeded",
            {},
        )


def test_send_billing_email(team):
    """Test sending billing email with template."""
    team, member = team
    subject = "Test Subject"
    template = "test_template"
    context = {"test_key": "test_value"}

    with patch("billing.email_notifications.render_to_string") as mock_render:
        mock_render.side_effect = ["html_content", "text_content"]
        with patch("billing.email_notifications.send_mail") as mock_send:
            email_notifications.send_billing_email(team, member, subject, template, context)
            mock_send.assert_called_once_with(
                subject,
                "text_content",
                None,  # DEFAULT_FROM_EMAIL
                [member.user.email],
                html_message="html_content",
                fail_silently=True,
            )
            assert mock_render.call_count == 2
            mock_render.assert_has_calls([
                mock.call(f"billing/emails/{template}.html", context),
                mock.call(f"billing/emails/{template}.txt", context),
            ])


def test_send_billing_email_template_error(team):
    """Test sending billing email with template error."""
    team, member = team
    subject = "Test Subject"
    template = "non_existent_template"
    context = {"test_key": "test_value"}

    with patch("billing.email_notifications.render_to_string", side_effect=Exception("Template error")):
        with patch("billing.email_notifications.logger") as mock_logger:
            email_notifications.send_billing_email(team, member, subject, template, context)
            mock_logger.error.assert_called_once()


def test_send_billing_email_send_error(team):
    """Test sending billing email with send error."""
    team, member = team
    subject = "Test Subject"
    template = "test_template"
    context = {"test_key": "test_value"}

    with patch("billing.email_notifications.render_to_string") as mock_render:
        mock_render.side_effect = ["html_content", "text_content"]
        with patch("billing.email_notifications.send_mail", side_effect=Exception("Send error")):
            with patch("billing.email_notifications.logger") as mock_logger:
                email_notifications.send_billing_email(team, member, subject, template, context)
                mock_logger.error.assert_called_once()


def test_send_billing_email_invalid_team(team):
    """Test sending billing email with invalid team."""
    team, member = team
    subject = "Test Subject"
    template = "test_template"
    context = {"test_key": "test_value"}

    # Set team to None to simulate invalid team
    team = None

    with patch("billing.email_notifications.logger") as mock_logger:
        email_notifications.send_billing_email(team, member, subject, template, context)
        mock_logger.error.assert_called_once()


def test_send_billing_email_invalid_member(team):
    """Test sending billing email with invalid member."""
    team, member = team
    subject = "Test Subject"
    template = "test_template"
    context = {"test_key": "test_value"}

    # Set member to None to simulate invalid member
    member = None

    with patch("billing.email_notifications.logger") as mock_logger:
        email_notifications.send_billing_email(team, member, subject, template, context)
        mock_logger.error.assert_called_once()