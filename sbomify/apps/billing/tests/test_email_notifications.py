"""Tests for billing email notifications."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from sbomify.apps.billing import email_notifications
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def team(db):
    """Create a test team with a member."""
    team = Team.objects.create(name="Test Team")
    team.key = number_to_random_token(team.pk)
    team.save()
    user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
    member = Member.objects.create(team=team, user=user, role="owner")
    return team, member


def test_notify_trial_ending(team):
    """Test trial ending notification."""
    team, member = team
    days_remaining = 3

    with patch("sbomify.apps.billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_trial_ending(team, member, days_remaining)
        mock_send.assert_called_once_with(
            team,
            member,
            f"Your sbomify trial ends in {days_remaining} days",
            "trial_ending",
            {"days_remaining": days_remaining},
        )


def test_notify_payment_failed(team):
    """Test payment failed notification."""
    team, member = team
    invoice_id = "inv_123"

    with patch("sbomify.apps.billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_payment_failed(team, member, invoice_id)
        mock_send.assert_called_once_with(
            team,
            member,
            f"Payment failed for {team.name}",
            "payment_failed",
            {"invoice_id": invoice_id},
        )


def test_notify_payment_failed_no_invoice(team):
    """Test payment failed notification without invoice ID."""
    team, member = team

    with patch("sbomify.apps.billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_payment_failed(team, member, None)
        mock_send.assert_called_once_with(
            team,
            member,
            f"Payment failed for {team.name}",
            "payment_failed",
            {"invoice_id": None},
        )


def test_notify_payment_past_due(team):
    """Test payment past due notification."""
    team, member = team

    with patch("sbomify.apps.billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_payment_past_due(team, member)
        mock_send.assert_called_once_with(
            team,
            member,
            f"Payment past due for {team.name}",
            "payment_past_due",
            {},
        )


def test_notify_subscription_cancelled(team):
    """Test subscription cancelled notification."""
    team, member = team

    with patch("sbomify.apps.billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_subscription_cancelled(team, member)
        mock_send.assert_called_once_with(
            team,
            member,
            "Your sbomify subscription has been cancelled",
            "subscription_cancelled",
            {},
        )


def test_notify_payment_succeeded(team):
    """Test payment succeeded notification."""
    team, member = team

    with patch("sbomify.apps.billing.email_notifications.send_billing_email") as mock_send:
        email_notifications.notify_payment_succeeded(team, member)
        mock_send.assert_called_once_with(
            team,
            member,
            f"Payment received for {team.name}",
            "payment_succeeded",
            {},
        )


def test_send_billing_email(team):
    """Test sending billing email with template."""
    team, member = team
    subject = "Test Subject"
    template = "test_template"
    extra_context = {"test_key": "test_value"}

    with patch("sbomify.apps.billing.email_notifications._get_billing_portal_url") as mock_portal_url:
        mock_portal_url.return_value = "https://app.sbomify.com/billing/portal/test"
        with patch("sbomify.apps.billing.email_notifications._get_select_plan_url") as mock_plan_url:
            mock_plan_url.return_value = "https://app.sbomify.com/billing/select-plan/test"
            with patch("sbomify.apps.billing.email_notifications.render_to_string") as mock_render:
                mock_render.side_effect = ["html_content", "text_content"]
                with patch("sbomify.apps.billing.email_notifications.send_mail") as mock_send:
                    email_notifications.send_billing_email(team, member, subject, template, extra_context)
                    mock_send.assert_called_once_with(
                        subject,
                        "text_content",
                        None,  # DEFAULT_FROM_EMAIL
                        [member.user.email],
                        html_message="html_content",
                        fail_silently=True,
                    )
                    assert mock_render.call_count == 2
                    # Verify the context includes both base and extra context
                    call_args = mock_render.call_args_list[0]
                    rendered_context = call_args[0][1]
                    assert rendered_context["test_key"] == "test_value"
                    assert rendered_context["user_name"] == member.user.email
                    assert rendered_context["team_name"] == team.name


def test_send_billing_email_template_error(team):
    """Test sending billing email with template error."""
    team, member = team
    subject = "Test Subject"
    template = "non_existent_template"
    context = {"test_key": "test_value"}

    with patch("sbomify.apps.billing.email_notifications.render_to_string", side_effect=Exception("Template error")):
        with patch("sbomify.apps.billing.email_notifications.logger") as mock_logger:
            email_notifications.send_billing_email(team, member, subject, template, context)
            mock_logger.error.assert_called_once()


def test_send_billing_email_send_error(team):
    """Test sending billing email with send error."""
    team, member = team
    subject = "Test Subject"
    template = "test_template"
    context = {"test_key": "test_value"}

    with patch("sbomify.apps.billing.email_notifications.render_to_string") as mock_render:
        mock_render.side_effect = ["html_content", "text_content"]
        with patch("sbomify.apps.billing.email_notifications.send_mail", side_effect=Exception("Send error")):
            with patch("sbomify.apps.billing.email_notifications.logger") as mock_logger:
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

    with patch("sbomify.apps.billing.email_notifications.logger") as mock_logger:
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

    with patch("sbomify.apps.billing.email_notifications.logger") as mock_logger:
        email_notifications.send_billing_email(team, member, subject, template, context)
        mock_logger.error.assert_called_once()
