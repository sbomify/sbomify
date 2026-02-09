"""
Management command to send test emails for all email templates.
Usage: uv run python manage.py send_test_emails
"""

from datetime import datetime

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string


class Command(BaseCommand):
    help = "Send test emails for all email templates to MailHog"

    def add_arguments(self, parser):
        parser.add_argument(
            "--recipient",
            type=str,
            default="test@example.com",
            help="Email address to send test emails to (default: test@example.com)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force sending even in non-DEBUG mode (use with caution)",
        )

    def handle(self, *args, **options):
        # Safety check: only allow in DEBUG mode unless --force is used
        if not settings.DEBUG and not options["force"]:
            self.stdout.write(
                self.style.ERROR(
                    "This command is intended for development/testing only. "
                    "To run in production, use --force flag (not recommended)."
                )
            )
            return

        base_url = getattr(settings, "APP_BASE_URL", "http://localhost:8000").rstrip("/")
        recipient = options["recipient"]

        # Mock data for templates
        mock_team = type("Team", (), {"name": "Acme Corp", "key": "acme-corp"})()
        mock_user = type(
            "User",
            (),
            {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john.doe@example.com",
                "username": "johndoe",
                "get_full_name": lambda self: f"{self.first_name} {self.last_name}",
            },
        )()
        mock_admin = type(
            "Admin",
            (),
            {"first_name": "Admin", "last_name": "User", "email": "admin@example.com"},
        )()
        mock_invitation = type(
            "Invitation",
            (),
            {"token": "abc123", "expires_at": datetime(2025, 12, 31), "role": "guest"},
        )()

        emails_sent = 0
        emails_failed = 0

        # Define all test emails
        test_emails = [
            # Billing emails
            {
                "subject": "Payment failed for Acme Corp",
                "template_html": "billing/emails/payment_failed.html.j2",
                "template_txt": "billing/emails/payment_failed.txt",
                "context": {
                    "user_name": "John Doe",
                    "team_name": "Acme Corp",
                    "base_url": base_url,
                    "action_url": f"{base_url}/billing/portal/acme-corp/",
                    "upgrade_url": f"{base_url}/billing/select-plan/acme-corp/",
                    "invoice_id": "inv_123456",
                },
            },
            {
                "subject": "Payment past due for Acme Corp",
                "template_html": "billing/emails/payment_past_due.html.j2",
                "template_txt": "billing/emails/payment_past_due.txt",
                "context": {
                    "user_name": "John Doe",
                    "team_name": "Acme Corp",
                    "base_url": base_url,
                    "action_url": f"{base_url}/billing/portal/acme-corp/",
                    "upgrade_url": f"{base_url}/billing/select-plan/acme-corp/",
                },
            },
            {
                "subject": "Payment received for Acme Corp",
                "template_html": "billing/emails/payment_succeeded.html.j2",
                "template_txt": "billing/emails/payment_succeeded.txt",
                "context": {
                    "user_name": "John Doe",
                    "team_name": "Acme Corp",
                    "base_url": base_url,
                    "action_url": f"{base_url}/billing/portal/acme-corp/",
                    "upgrade_url": f"{base_url}/billing/select-plan/acme-corp/",
                },
            },
            {
                "subject": "Your sbomify subscription has been cancelled",
                "template_html": "billing/emails/subscription_cancelled.html.j2",
                "template_txt": "billing/emails/subscription_cancelled.txt",
                "context": {
                    "user_name": "John Doe",
                    "team_name": "Acme Corp",
                    "base_url": base_url,
                    "action_url": f"{base_url}/billing/portal/acme-corp/",
                    "upgrade_url": f"{base_url}/billing/select-plan/acme-corp/",
                },
            },
            {
                "subject": "Your sbomify subscription has ended",
                "template_html": "billing/emails/subscription_ended.html.j2",
                "template_txt": "billing/emails/subscription_ended.txt",
                "context": {
                    "user_name": "John Doe",
                    "team_name": "Acme Corp",
                    "base_url": base_url,
                    "action_url": f"{base_url}/billing/portal/acme-corp/",
                    "upgrade_url": f"{base_url}/billing/select-plan/acme-corp/",
                },
            },
            {
                "subject": "Your sbomify trial ends in 3 days",
                "template_html": "billing/emails/trial_ending.html.j2",
                "template_txt": "billing/emails/trial_ending.txt",
                "context": {
                    "user_name": "John Doe",
                    "team_name": "Acme Corp",
                    "base_url": base_url,
                    "action_url": f"{base_url}/billing/portal/acme-corp/",
                    "upgrade_url": f"{base_url}/billing/select-plan/acme-corp/",
                    "days_remaining": 3,
                },
            },
            {
                "subject": "Your sbomify trial has expired",
                "template_html": "billing/emails/trial_expired.html.j2",
                "template_txt": "billing/emails/trial_expired.txt",
                "context": {
                    "user_name": "John Doe",
                    "team_name": "Acme Corp",
                    "base_url": base_url,
                    "action_url": f"{base_url}/billing/portal/acme-corp/",
                    "upgrade_url": f"{base_url}/billing/select-plan/acme-corp/",
                },
            },
            # Document access emails
            {
                "subject": "New Access Request",
                "template_html": "documents/emails/access_request_notification.html.j2",
                "template_txt": "documents/emails/access_request_notification.txt",
                "context": {
                    "admin_user": mock_admin,
                    "team": mock_team,
                    "base_url": base_url,
                    "requester_name": "Jane Smith",
                    "requester_email": "jane.smith@example.com",
                    "requested_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "requires_nda": True,
                    "nda_signed": False,
                    "review_link": f"{base_url}/workspaces/acme-corp#trust-center",
                },
            },
            {
                "subject": "Your Access Request Has Been Approved",
                "template_html": "documents/emails/access_approved.html.j2",
                "template_txt": "documents/emails/access_approved.txt",
                "context": {
                    "user": mock_user,
                    "team": mock_team,
                    "base_url": base_url,
                    "login_link": f"{base_url}/login",
                },
            },
            {
                "subject": "Your Access Request Has Been Rejected",
                "template_html": "documents/emails/access_rejected.html.j2",
                "template_txt": "documents/emails/access_rejected.txt",
                "context": {
                    "user": mock_user,
                    "team": mock_team,
                    "base_url": base_url,
                },
            },
            {
                "subject": "Your Access Has Been Revoked",
                "template_html": "documents/emails/access_revoked.html.j2",
                "template_txt": "documents/emails/access_revoked.txt",
                "context": {
                    "user": mock_user,
                    "team": mock_team,
                    "base_url": base_url,
                },
            },
            # Team emails
            {
                "subject": "You have been invited to join a workspace on sbomify",
                "template_html": "teams/emails/team_invite_email.html.j2",
                "template_txt": "teams/emails/team_invite_email.txt",
                "context": {
                    "user": mock_user,
                    "team": mock_team,
                    "invitation": mock_invitation,
                    "base_url": base_url,
                },
            },
            {
                "subject": "You have been invited to view Trust Center on sbomify",
                "template_html": "teams/emails/trust_center_invite_email.html.j2",
                "template_txt": "teams/emails/trust_center_invite_email.txt",
                "context": {
                    "user": mock_user,
                    "team": mock_team,
                    "invitation": mock_invitation,
                    "base_url": base_url,
                },
            },
            # Onboarding emails
            {
                "subject": "Welcome to sbomify - Let's Get Started!",
                "template_html": "onboarding/emails/welcome.html.j2",
                "template_txt": "onboarding/emails/welcome.txt",
                "context": {
                    "user": mock_user,
                    "user_role": "owner",
                    "workspace_name": "Acme Corp",
                    "app_base_url": base_url,
                },
            },
        ]

        for email_config in test_emails:
            try:
                html_message = render_to_string(email_config["template_html"], email_config["context"])
                plain_message = render_to_string(email_config["template_txt"], email_config["context"])

                send_mail(
                    email_config["subject"],
                    plain_message,
                    None,
                    [recipient],
                    html_message=html_message,
                    fail_silently=False,
                )
                self.stdout.write(self.style.SUCCESS(f"Sent: {email_config['subject']}"))
                emails_sent += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed: {email_config['subject']} - {e}"))
                emails_failed += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Emails sent: {emails_sent}/{len(test_emails)}"))
        if emails_failed > 0:
            self.stdout.write(self.style.ERROR(f"Emails failed: {emails_failed}"))
        self.stdout.write("")
        self.stdout.write("Check MailHog at http://localhost:8025 to view the emails")
