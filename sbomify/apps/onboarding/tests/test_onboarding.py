"""
Tests for onboarding functionality using pytest and existing fixtures.
"""

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError
from django.utils import timezone

from sbomify.apps.core.models import Component
from sbomify.apps.onboarding.models import OnboardingEmail, OnboardingStatus
from sbomify.apps.onboarding.services import OnboardingEmailService
from sbomify.apps.onboarding.tasks import (
    process_onboarding_sequence_batch_task,
    queue_welcome_email,
    send_collaboration_email_task,
    send_first_component_email_task,
    send_first_sbom_email_task,
    send_quick_start_email_task,
    send_welcome_email_task,
)
from sbomify.apps.onboarding.utils import get_email_context, html_to_plain_text, render_email_templates
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member, Team

User = get_user_model()

# Import existing fixtures from the shared fixture system
pytest_plugins = [
    "sbomify.apps.core.tests.fixtures",
    "sbomify.apps.teams.fixtures",
    "sbomify.apps.sboms.tests.fixtures",
]


@pytest.mark.django_db
class TestOnboardingStatusModel:
    """Test OnboardingStatus model functionality."""

    def test_onboarding_status_creation(self, sample_user) -> None:
        """Test OnboardingStatus is created with correct defaults."""
        # OnboardingStatus should already exist due to signal, so get it
        status = OnboardingStatus.objects.get(user=sample_user)

        assert not status.has_created_component
        assert not status.has_uploaded_sbom
        assert not status.has_completed_wizard
        assert not status.welcome_email_sent
        assert status.first_component_created_at is None
        assert status.first_sbom_uploaded_at is None

    def test_mark_component_created(self, sample_user) -> None:
        """Test marking component as created."""
        status = OnboardingStatus.objects.get(user=sample_user)
        assert not status.has_created_component
        assert status.first_component_created_at is None

        status.mark_component_created()

        assert status.has_created_component
        assert status.first_component_created_at is not None

        # Should not update timestamp on subsequent calls
        original_time = status.first_component_created_at
        status.mark_component_created()
        assert status.first_component_created_at == original_time

    def test_mark_sbom_uploaded(self, sample_user) -> None:
        """Test marking SBOM as uploaded."""
        status = OnboardingStatus.objects.get(user=sample_user)
        assert not status.has_uploaded_sbom
        assert status.first_sbom_uploaded_at is None

        status.mark_sbom_uploaded()

        assert status.has_uploaded_sbom
        assert status.first_sbom_uploaded_at is not None

    def test_user_role_property(self, sample_user, sample_team_with_owner_member) -> None:
        """Test user_role property returns correct role."""
        status = OnboardingStatus.objects.get(user=sample_user)

        # User should be owner due to sample_team_with_owner_member fixture
        assert status.user_role == "owner"

    def test_days_since_signup(self, sample_user) -> None:
        """Test days_since_signup calculation."""
        status = OnboardingStatus.objects.get(user=sample_user)

        # Set creation time to 5 days ago
        past_time = timezone.now() - timedelta(days=5)
        status.created_at = past_time
        status.save()

        assert status.days_since_signup == 5

    def test_should_receive_component_reminder_workspace_owner(self) -> None:
        """Test component reminder logic for workspace owners."""
        # Create a fresh user and team to avoid fixture conflicts
        test_user = User.objects.create_user(
            username="componenttest", email="componenttest@example.com", password="testpass123"
        )
        test_team = Team.objects.create(name="Component Test Team", key="comp-test-team")
        Member.objects.create(user=test_user, team=test_team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=test_user)

        # Should not receive if welcome email not sent
        assert not status.should_receive_component_reminder()

        # Mark welcome email sent but not enough days passed
        status.mark_welcome_email_sent()
        assert not status.should_receive_component_reminder(days_threshold=3)

        # Set creation time to 4 days ago
        past_time = timezone.now() - timedelta(days=4)
        status.created_at = past_time
        status.save()

        # Verify the team has no components initially
        assert test_team.component_set.count() == 0

        # Should receive reminder now (workspace has no components)
        assert status.should_receive_component_reminder(days_threshold=3)

        # Should not receive if workspace has components
        Component.objects.create(name="test-component", team=test_team)
        assert not status.should_receive_component_reminder(days_threshold=3)

    def test_should_receive_sbom_reminder_workspace_owner(self) -> None:
        """Test SBOM reminder logic for workspace owners."""
        # Create a fresh user and team to avoid fixture conflicts
        test_user = User.objects.create_user(username="sbomtest", email="sbomtest@example.com", password="testpass123")
        test_team = Team.objects.create(name="SBOM Test Team", key="sbom-test-team")
        Member.objects.create(user=test_user, team=test_team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=test_user)
        status.mark_component_created()

        # Create a component in the workspace
        component = Component.objects.create(name="test-component", team=test_team)

        # Should not receive immediately (not enough days passed)
        assert not status.should_receive_sbom_reminder(days_threshold=7)

        # Set component creation time to 8 days ago
        past_time = timezone.now() - timedelta(days=8)
        status.first_component_created_at = past_time
        status.save()

        # Should receive reminder now (workspace has components but no SBOMs)
        assert status.should_receive_sbom_reminder(days_threshold=7)

        # Should not receive if workspace has SBOMs
        SBOM.objects.create(name="test-sbom", component=component)
        assert not status.should_receive_sbom_reminder(days_threshold=7)

    def test_drip_clock_anchors_on_drip_started_at(self) -> None:
        """Drip eligibility uses `drip_started_at`, not signup, as the clock.

        This is what lets a long-dormant scheduler start sending the full
        sequence to backlog users without firing every email simultaneously
        — the migration resets `drip_started_at` to deploy time.
        """
        test_user = User.objects.create_user(
            username="dripclock", email="dripclock@example.com", password="testpass123"
        )
        test_team = Team.objects.create(name="Drip Clock Team", key="drip-clock-team")
        Member.objects.create(user=test_user, team=test_team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=test_user)
        # Backlog scenario: signup 90d ago, but drip clock only just started
        status.created_at = timezone.now() - timedelta(days=90)
        status.welcome_email_sent = True
        status.drip_started_at = timezone.now()  # equivalent to migration backfill
        status.save()

        # Day 0 of drip — none eligible yet
        assert not status.should_receive_quick_start()
        assert not status.should_receive_component_reminder()
        assert not status.should_receive_collaboration()

        # Day 1 of drip — quick_start eligible, others not
        status.drip_started_at = timezone.now() - timedelta(days=1)
        status.save()
        assert status.should_receive_quick_start()
        assert not status.should_receive_component_reminder()
        assert not status.should_receive_collaboration()

        # Day 3 of drip — first_component eligible (no component in workspace)
        status.drip_started_at = timezone.now() - timedelta(days=3)
        status.save()
        assert status.should_receive_component_reminder()
        assert not status.should_receive_collaboration()

        # Day 10 of drip — collaboration eligible (solo workspace)
        status.drip_started_at = timezone.now() - timedelta(days=10)
        status.save()
        assert status.should_receive_collaboration()


@pytest.mark.django_db
class TestOnboardingEmailModel:
    """Test OnboardingEmail model functionality."""

    def test_email_creation(self, sample_user) -> None:
        """Test OnboardingEmail creation."""
        email = OnboardingEmail.create_email(
            user=sample_user, email_type=OnboardingEmail.EmailType.WELCOME, subject="Welcome!"
        )

        assert email.user == sample_user
        assert email.email_type == OnboardingEmail.EmailType.WELCOME
        assert email.subject == "Welcome!"
        assert email.status == OnboardingEmail.EmailStatus.PENDING

    def test_mark_sent(self, sample_user) -> None:
        """Test marking email as sent."""
        email = OnboardingEmail.create_email(
            user=sample_user, email_type=OnboardingEmail.EmailType.WELCOME, subject="Welcome!"
        )

        assert email.status == OnboardingEmail.EmailStatus.PENDING
        assert email.sent_at is None

        email.mark_sent()

        assert email.status == OnboardingEmail.EmailStatus.SENT
        assert email.sent_at is not None

    def test_mark_failed(self, sample_user) -> None:
        """Test marking email as failed."""
        email = OnboardingEmail.create_email(
            user=sample_user, email_type=OnboardingEmail.EmailType.WELCOME, subject="Welcome!"
        )

        error_message = "SMTP connection failed"
        email.mark_failed(error_message)

        assert email.status == OnboardingEmail.EmailStatus.FAILED
        assert email.error_message == error_message
        assert email.retry_count == 1

    def test_unique_constraint(self) -> None:
        """Test unique constraint on user and email_type."""
        # Create a fresh user for this test to avoid conflicts
        test_user = User.objects.create_user(username="uniquetest", email="unique@example.com", password="testpass123")

        OnboardingEmail.create_email(user=test_user, email_type=OnboardingEmail.EmailType.WELCOME, subject="Welcome!")

        # Should not be able to create another welcome email for same user
        with pytest.raises(IntegrityError):
            OnboardingEmail.create_email(
                user=test_user, email_type=OnboardingEmail.EmailType.WELCOME, subject="Welcome Again!"
            )


class TestHtmlToPlainText:
    """Test HTML to plain text conversion."""

    def test_basic_conversion(self) -> None:
        """Test basic HTML to plain text conversion."""
        html = "<p>Hello <strong>world</strong>!</p>"
        plain_text = html_to_plain_text(html)

        assert "Hello world!" in plain_text
        assert "<p>" not in plain_text
        assert "<strong>" not in plain_text

    def test_headers_conversion(self) -> None:
        """Test header conversion."""
        html = "<h1>Main Title</h1><h2>Subtitle</h2><h3>Section</h3>"
        plain_text = html_to_plain_text(html)

        assert "Main Title" in plain_text
        assert "=" * 50 in plain_text  # h1 underline
        assert "Subtitle" in plain_text
        assert "-" * 30 in plain_text  # h2 underline
        assert "Section:" in plain_text  # h3 with colon

    def test_links_conversion(self) -> None:
        """Test link conversion."""
        html = '<a href="https://example.com">Click here</a>'
        plain_text = html_to_plain_text(html)

        assert "Click here (https://example.com)" in plain_text

    def test_lists_conversion(self) -> None:
        """Test list conversion."""
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        plain_text = html_to_plain_text(html)

        assert "• Item 1" in plain_text
        assert "• Item 2" in plain_text

    def test_highlight_box_conversion(self) -> None:
        """Test highlight box conversion."""
        html = '<div class="highlight-box"><h3>Pro Tip</h3><p>This is important!</p></div>'
        plain_text = html_to_plain_text(html)

        assert "Pro Tip:" in plain_text
        assert "This is important!" in plain_text
        assert "---" in plain_text


@pytest.mark.django_db
class TestEmailTemplateRendering:
    """Test email template rendering."""

    def test_get_email_context(self, sample_user, sample_team_with_owner_member) -> None:
        """Test email context generation."""
        context = get_email_context(sample_user)

        assert context["user"] == sample_user
        assert context["user_role"] == "owner"
        assert context["workspace_name"] == sample_team_with_owner_member.team.name
        assert context["workspace_key"] == sample_team_with_owner_member.team.key
        assert "app_base_url" in context
        assert "website_base_url" in context

    @patch("sbomify.apps.onboarding.utils.render_to_string")
    def test_render_email_templates(self, mock_render: MagicMock, sample_user) -> None:
        """Test email template rendering."""
        mock_html = "<h1>Welcome {{ user.username }}!</h1>"
        mock_render.return_value = mock_html

        context = {"user": sample_user}
        html_content, plain_text_content = render_email_templates("welcome", context)

        assert html_content == mock_html
        assert "Welcome" in plain_text_content
        assert "<h1>" not in plain_text_content

        mock_render.assert_called_once_with("onboarding/emails/welcome.html.j2", context)


@pytest.mark.django_db
class TestOnboardingEmailService:
    """Test OnboardingEmailService functionality."""

    def test_send_welcome_email_success(self, sample_user, sample_team_with_owner_member) -> None:
        """Test successful welcome email sending."""
        # Clear any existing emails
        mail.outbox = []

        result = OnboardingEmailService.send_welcome_email(sample_user)

        assert result is True
        assert len(mail.outbox) == 1

        # Check email content
        email = mail.outbox[0]
        assert email.to == [sample_user.email]
        assert "Welcome to sbomify" in email.subject
        assert "Test" in email.body  # Plain text version (uses first_name from fixture)
        assert "Test" in email.alternatives[0][0]  # HTML version

        # Check database records
        onboarding_status = OnboardingStatus.objects.get(user=sample_user)
        assert onboarding_status.welcome_email_sent

        email_record = OnboardingEmail.objects.get(user=sample_user, email_type=OnboardingEmail.EmailType.WELCOME)
        assert email_record.status == OnboardingEmail.EmailStatus.SENT

    def test_send_welcome_email_already_sent(self, sample_user) -> None:
        """Test welcome email not sent if already sent."""
        # Mark welcome email as already sent
        onboarding_status = OnboardingStatus.objects.get(user=sample_user)
        onboarding_status.mark_welcome_email_sent()

        mail.outbox = []

        result = OnboardingEmailService.send_welcome_email(sample_user)

        assert result is True  # Returns True but doesn't send
        assert len(mail.outbox) == 0

    @patch("sbomify.apps.onboarding.services.EmailMultiAlternatives")
    def test_send_email_failure_handling(self, mock_send_mail: MagicMock, sample_user) -> None:
        """Test email sending failure handling."""
        mock_send_mail.side_effect = Exception("SMTP Error")

        result = OnboardingEmailService.send_welcome_email(sample_user)

        assert result is False

        # Check that failure is recorded
        email_record = OnboardingEmail.objects.get(user=sample_user, email_type=OnboardingEmail.EmailType.WELCOME)
        assert email_record.status == OnboardingEmail.EmailStatus.FAILED
        assert "SMTP send failure: Exception" in email_record.error_message


@pytest.mark.django_db
class TestOnboardingTasks:
    """Test Dramatiq tasks for onboarding emails."""

    def test_send_welcome_email_task_success(self, sample_user, sample_team_with_owner_member) -> None:
        """Test successful welcome email task execution."""
        mail.outbox = []

        # Execute task directly (not through Dramatiq)
        send_welcome_email_task(sample_user.id)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [sample_user.email]

    def test_send_welcome_email_task_user_not_found(self) -> None:
        """Test welcome email task with non-existent user gracefully exits."""
        # Should not raise an exception, just log and return
        send_welcome_email_task(99999)  # Non-existent user ID
        # No assertion needed - we just verify it doesn't raise

    @patch("sbomify.apps.onboarding.tasks.send_welcome_email_task")
    def test_queue_welcome_email(self, mock_task: MagicMock, sample_user) -> None:
        """Test queueing welcome email task."""
        mock_task.send_with_options.return_value = MagicMock(message_id="test-message-id")

        message_id = queue_welcome_email(sample_user)

        assert message_id == "test-message-id"
        mock_task.send_with_options.assert_called_once_with(args=(sample_user.id,), delay=10000)


@pytest.mark.django_db
class TestOnboardingSignals:
    """Test onboarding signal handlers."""

    def test_onboarding_status_created_on_user_creation(self) -> None:
        """Test OnboardingStatus is created when user is created."""
        new_user = User.objects.create_user(username="newuser", email="new@example.com", password="testpass123")

        # OnboardingStatus should be created automatically
        assert OnboardingStatus.objects.filter(user=new_user).exists()

    def test_component_creation_tracking(self) -> None:
        """Test component creation is tracked in onboarding status."""
        # Create fresh user/team to ensure this is the first component
        test_user = User.objects.create_user(username="comptrack", email="comptrack@example.com", password="test123")
        test_team = Team.objects.create(name="Track Team", key="track-team")
        Member.objects.create(user=test_user, team=test_team, role="owner", is_default_team=True)

        # Get onboarding status (created by signal)
        onboarding_status = OnboardingStatus.objects.get(user=test_user)
        assert not onboarding_status.has_created_component

        # Ensure team has no components initially
        assert test_team.component_set.count() == 0

        # Create component (should trigger signal since it's the first one)
        Component.objects.create(name="test-component", team=test_team)

        # Check that onboarding status is updated
        onboarding_status.refresh_from_db()
        assert onboarding_status.has_created_component
        assert onboarding_status.first_component_created_at is not None

    def test_sbom_upload_tracking(self) -> None:
        """Test SBOM upload is tracked in onboarding status."""
        # Create fresh user/team/component to ensure this is the first SBOM
        test_user = User.objects.create_user(username="sbomtrack", email="sbomtrack@example.com", password="test123")
        test_team = Team.objects.create(name="SBOM Track Team", key="sbom-track-team")
        Member.objects.create(user=test_user, team=test_team, role="owner", is_default_team=True)
        test_component = Component.objects.create(name="track-component", team=test_team)

        # Get onboarding status (created by signal)
        onboarding_status = OnboardingStatus.objects.get(user=test_user)
        assert not onboarding_status.has_uploaded_sbom

        # Ensure workspace has no SBOMs initially
        assert SBOM.objects.filter(component__team=test_team).count() == 0

        # Create SBOM (should trigger signal since it's the first one in workspace)
        SBOM.objects.create(name="test-sbom", component=test_component)

        # Check that onboarding status is updated
        onboarding_status.refresh_from_db()
        assert onboarding_status.has_uploaded_sbom
        assert onboarding_status.first_sbom_uploaded_at is not None


@pytest.mark.django_db
class TestOnboardingIntegration:
    """Integration tests for the complete onboarding flow."""

    def test_complete_onboarding_flow(self) -> None:
        """Test the complete onboarding email flow."""
        # Create fresh user/team to avoid fixture conflicts
        test_user = User.objects.create_user(username="flowtest", email="flowtest@example.com", password="test123")
        test_team = Team.objects.create(name="Flow Team", key="flow-team")
        Member.objects.create(user=test_user, team=test_team, role="owner", is_default_team=True)

        # OnboardingStatus should be created automatically
        onboarding_status = OnboardingStatus.objects.get(user=test_user)
        assert not onboarding_status.welcome_email_sent

        # Send welcome email
        result = OnboardingEmailService.send_welcome_email(test_user)
        assert result is True

        # Check welcome email was marked as sent
        onboarding_status.refresh_from_db()
        assert onboarding_status.welcome_email_sent

        # Simulate time passing and component creation eligibility
        onboarding_status.created_at = timezone.now() - timedelta(days=4)
        onboarding_status.save()

        # Should be eligible for component reminder
        assert onboarding_status.should_receive_component_reminder(days_threshold=3)

        # Send the day-3 first-component reminder
        result = OnboardingEmailService.send_first_component_email(test_user)
        assert result is True

        # Create component to simulate user action
        component = Component.objects.create(name="test-component", team=test_team)

        # Check component creation was tracked
        onboarding_status.refresh_from_db()
        assert onboarding_status.has_created_component

        # Simulate time passing for SBOM reminder
        onboarding_status.first_component_created_at = timezone.now() - timedelta(days=8)
        onboarding_status.save()

        # Should be eligible for SBOM reminder
        assert onboarding_status.should_receive_sbom_reminder(days_threshold=7)

        # Create SBOM to complete the flow
        SBOM.objects.create(name="test-sbom", component=component)

        # Check SBOM upload was tracked
        onboarding_status.refresh_from_db()
        assert onboarding_status.has_uploaded_sbom

        # Should no longer be eligible for SBOM reminder
        assert not onboarding_status.should_receive_sbom_reminder(days_threshold=7)


@pytest.mark.django_db
class TestOnboardingStatusSequenceMethods:
    """Test new onboarding sequence eligibility methods on OnboardingStatus."""

    def test_should_receive_quick_start_not_welcome_sent(self) -> None:
        """Quick start not sent if welcome email not sent."""
        user = User.objects.create_user(username="qs1", email="qs1@example.com", password="test123")
        status = OnboardingStatus.objects.get(user=user)
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        assert not status.should_receive_quick_start()

    def test_should_receive_quick_start_too_early(self) -> None:
        """Quick start not sent if signup was less than 1 day ago."""
        user = User.objects.create_user(username="qs2", email="qs2@example.com", password="test123")
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()

        # days_since_signup == 0 (just created)
        assert not status.should_receive_quick_start(days_threshold=1)

    def test_should_receive_quick_start_eligible(self) -> None:
        """Quick start sent after 1+ days with welcome sent and owner role."""
        user = User.objects.create_user(username="qs3", email="qs3@example.com", password="test123")
        team = Team.objects.create(name="QS3 Team", key="qs3-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        assert status.should_receive_quick_start(days_threshold=1)

    def test_should_receive_collaboration_not_welcome_sent(self) -> None:
        """Collaboration not sent if welcome email not sent."""
        user = User.objects.create_user(username="col1", email="col1@example.com", password="test123")
        team = Team.objects.create(name="Col Team 1", key="col-team-1")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.created_at = timezone.now() - timedelta(days=15)
        status.save()

        assert not status.should_receive_collaboration()

    def test_should_receive_collaboration_too_early(self) -> None:
        """Collaboration not sent if less than 10 days since signup."""
        user = User.objects.create_user(username="col2", email="col2@example.com", password="test123")
        team = Team.objects.create(name="Col Team 2", key="col-team-2")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=5)
        status.save()

        assert not status.should_receive_collaboration(days_threshold=10)

    def test_should_receive_collaboration_not_owner(self) -> None:
        """Collaboration not sent to non-owners."""
        user = User.objects.create_user(username="col3", email="col3@example.com", password="test123")
        team = Team.objects.create(name="Col Team 3", key="col-team-3")
        Member.objects.create(user=user, team=team, role="member", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=15)
        status.save()

        assert not status.should_receive_collaboration()

    def test_should_receive_collaboration_multi_member_workspace(self) -> None:
        """Collaboration not sent if workspace already has multiple members."""
        user = User.objects.create_user(username="col4", email="col4@example.com", password="test123")
        user2 = User.objects.create_user(username="col4b", email="col4b@example.com", password="test123")
        team = Team.objects.create(name="Col Team 4", key="col-team-4")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        Member.objects.create(user=user2, team=team, role="member")

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=15)
        status.save()

        assert not status.should_receive_collaboration()

    def test_should_receive_collaboration_eligible(self) -> None:
        """Collaboration sent to solo workspace owner after 10+ days."""
        user = User.objects.create_user(username="col5", email="col5@example.com", password="test123")
        team = Team.objects.create(name="Col Team 5", key="col-team-5")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=12)
        status.save()

        assert status.should_receive_collaboration(days_threshold=10)


@pytest.mark.django_db
class TestOnboardingSequenceService:
    """Test OnboardingEmailService methods for the new email sequence."""

    def test_send_quick_start_email_success(self) -> None:
        """Test successful quick start email sending."""
        user = User.objects.create_user(
            username="qsvc1", email="qsvc1@example.com", password="test123", first_name="Quick"
        )
        team = Team.objects.create(name="QS Team", key="qs-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        # Set up eligibility: welcome sent + 2 days ago
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        mail.outbox = []
        result = OnboardingEmailService.send_quick_start_email(user)

        assert result is True
        assert len(mail.outbox) == 1
        assert "quick start" in mail.outbox[0].subject.lower()

        email_record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.QUICK_START)
        assert email_record.status == OnboardingEmail.EmailStatus.SENT

    def test_send_quick_start_email_already_sent(self) -> None:
        """Test quick start email not sent if already sent."""
        user = User.objects.create_user(username="qsvc2", email="qsvc2@example.com", password="test123")
        team = Team.objects.create(name="QS Team 2", key="qs-team-2")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        email_record = OnboardingEmail.create_email(
            user=user, email_type=OnboardingEmail.EmailType.QUICK_START, subject="Quick Start"
        )
        email_record.mark_sent()

        mail.outbox = []
        result = OnboardingEmailService.send_quick_start_email(user)

        assert result is True  # Returns True (already sent)
        assert len(mail.outbox) == 0

    def test_send_first_component_email_success(self) -> None:
        """Test successful first component email sending."""
        user = User.objects.create_user(
            username="fcsvc1", email="fcsvc1@example.com", password="test123", first_name="First"
        )
        team = Team.objects.create(name="FC Team", key="fc-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        # Set up eligibility: welcome sent + 4 days ago + no components
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=4)
        status.save()

        mail.outbox = []
        result = OnboardingEmailService.send_first_component_email(user)

        assert result is True
        assert len(mail.outbox) == 1
        assert "component" in mail.outbox[0].subject.lower()

        email_record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.FIRST_COMPONENT)
        assert email_record.status == OnboardingEmail.EmailStatus.SENT

    def test_send_first_sbom_email_success(self) -> None:
        """Test successful first SBOM email sending."""
        user = User.objects.create_user(
            username="fssvc1", email="fssvc1@example.com", password="test123", first_name="Sbom"
        )
        team = Team.objects.create(name="FS Team", key="fs-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        # Set up eligibility: component created 8 days ago + no SBOMs
        status = OnboardingStatus.objects.get(user=user)
        status.has_created_component = True
        status.first_component_created_at = timezone.now() - timedelta(days=8)
        status.created_at = timezone.now() - timedelta(days=10)
        status.save()

        mail.outbox = []
        result = OnboardingEmailService.send_first_sbom_email(user)

        assert result is True
        assert len(mail.outbox) == 1
        assert "sbom" in mail.outbox[0].subject.lower()

        email_record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.FIRST_SBOM)
        assert email_record.status == OnboardingEmail.EmailStatus.SENT

    def test_send_collaboration_email_success(self) -> None:
        """Test successful collaboration email sending."""
        user = User.objects.create_user(
            username="clsvc1", email="clsvc1@example.com", password="test123", first_name="Collab"
        )
        team = Team.objects.create(name="CL Team", key="cl-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        # Set up eligibility: welcome sent + 12 days ago + solo workspace
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=12)
        status.save()

        mail.outbox = []
        result = OnboardingEmailService.send_collaboration_email(user)

        assert result is True
        assert len(mail.outbox) == 1
        assert "invite" in mail.outbox[0].subject.lower() or "team" in mail.outbox[0].subject.lower()

        email_record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.COLLABORATION)
        assert email_record.status == OnboardingEmail.EmailStatus.SENT

    @patch("sbomify.apps.onboarding.services.EmailMultiAlternatives")
    def test_send_sequence_email_failure(self, mock_send_mail: MagicMock) -> None:
        """Test email failure handling in sequence emails."""
        mock_send_mail.side_effect = Exception("SMTP Error")

        user = User.objects.create_user(username="failsvc", email="failsvc@example.com", password="test123")
        team = Team.objects.create(name="Fail Team", key="fail-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        # Set up eligibility for quick_start
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        result = OnboardingEmailService.send_quick_start_email(user)

        assert result is False
        email_record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.QUICK_START)
        assert email_record.status == OnboardingEmail.EmailStatus.FAILED

    def test_retry_after_failure_succeeds(self) -> None:
        """Test that a failed email can be retried successfully on the next attempt."""
        user = User.objects.create_user(username="retrysvc", email="retrysvc@example.com", password="test123")
        team = Team.objects.create(name="Retry Team", key="retry-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        # First attempt: simulate SMTP send failure
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = Exception("SMTP Error")
            result = OnboardingEmailService.send_quick_start_email(user)
        assert result is False
        failed_record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.QUICK_START)
        assert failed_record.status == OnboardingEmail.EmailStatus.FAILED

        # Second attempt: should delete FAILED record, create new one, and send successfully
        mail.outbox = []
        result = OnboardingEmailService.send_quick_start_email(user)
        assert result is True
        assert len(mail.outbox) == 1
        sent_record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.QUICK_START)
        assert sent_record.status == OnboardingEmail.EmailStatus.SENT

    def test_integrity_error_concurrent_sent_returns_true(self) -> None:
        """Test that IntegrityError returns True when the concurrent record is SENT."""
        user = User.objects.create_user(username="racesvc", email="racesvc@example.com", password="test123")
        team = Team.objects.create(name="Race Team", key="race-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        # Simulate a concurrent worker that already sent the email
        concurrent_record = OnboardingEmail.create_email(
            user=user, email_type=OnboardingEmail.EmailType.QUICK_START, subject="Quick Start"
        )
        concurrent_record.mark_sent()

        mail.outbox = []
        result = OnboardingEmailService.send_quick_start_email(user)

        # Should return True because existing record is SENT (dedup check)
        assert result is True
        assert len(mail.outbox) == 0

    @patch("sbomify.apps.onboarding.services.OnboardingEmail.create_email")
    def test_integrity_error_concurrent_pending_returns_false(self, mock_create: MagicMock) -> None:
        """Test that IntegrityError returns False when concurrent record is not yet SENT."""
        mock_create.side_effect = IntegrityError("duplicate key")

        user = User.objects.create_user(username="racesvc2", email="racesvc2@example.com", password="test123")
        team = Team.objects.create(name="Race Team 2", key="race-team-2")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        mail.outbox = []
        result = OnboardingEmailService.send_quick_start_email(user)

        # Should return False because the concurrent record is not SENT
        assert result is False
        assert len(mail.outbox) == 0

    def test_get_users_for_onboarding_sequence(self, ensure_billing_plans) -> None:
        """Test getting eligible users for each onboarding sequence email."""
        # User 1: eligible for quick_start (day 2, welcome sent)
        user1 = User.objects.create_user(username="seq1", email="seq1@example.com")
        team1 = Team.objects.create(name="Seq Team 1", key="seq-team-1")
        Member.objects.create(user=user1, team=team1, role="owner", is_default_team=True)
        status1 = OnboardingStatus.objects.get(user=user1)
        status1.mark_welcome_email_sent()
        status1.created_at = timezone.now() - timedelta(days=2)
        status1.save()

        # User 2: eligible for first_component (day 4, no component)
        user2 = User.objects.create_user(username="seq2", email="seq2@example.com")
        team2 = Team.objects.create(name="Seq Team 2", key="seq-team-2")
        Member.objects.create(user=user2, team=team2, role="owner", is_default_team=True)
        status2 = OnboardingStatus.objects.get(user=user2)
        status2.mark_welcome_email_sent()
        status2.created_at = timezone.now() - timedelta(days=4)
        status2.save()

        # User 3: eligible for first_sbom (day 8, component but no SBOM)
        user3 = User.objects.create_user(username="seq3", email="seq3@example.com")
        team3 = Team.objects.create(name="Seq Team 3", key="seq-team-3")
        Member.objects.create(user=user3, team=team3, role="owner", is_default_team=True)
        Component.objects.create(name="seq-comp-3", team=team3)
        status3 = OnboardingStatus.objects.get(user=user3)
        status3.mark_welcome_email_sent()
        status3.mark_component_created()
        status3.first_component_created_at = timezone.now() - timedelta(days=8)
        status3.created_at = timezone.now() - timedelta(days=10)
        status3.save()

        # User 4: eligible for collaboration (day 12, solo workspace)
        user4 = User.objects.create_user(username="seq4", email="seq4@example.com")
        team4 = Team.objects.create(name="Seq Team 4", key="seq-team-4")
        Member.objects.create(user=user4, team=team4, role="owner", is_default_team=True)
        status4 = OnboardingStatus.objects.get(user=user4)
        status4.mark_welcome_email_sent()
        status4.created_at = timezone.now() - timedelta(days=12)
        status4.save()

        results = OnboardingEmailService.get_users_for_onboarding_sequence()

        # User 1 eligible for quick_start
        qs_ids = list(results[OnboardingEmail.EmailType.QUICK_START].values_list("id", flat=True))
        assert user1.id in qs_ids

        # User 2 eligible for first_component (also quick_start since day 4 > 1)
        fc_ids = list(results[OnboardingEmail.EmailType.FIRST_COMPONENT].values_list("id", flat=True))
        assert user2.id in fc_ids

        # User 3 eligible for first_sbom
        fs_ids = list(results[OnboardingEmail.EmailType.FIRST_SBOM].values_list("id", flat=True))
        assert user3.id in fs_ids

        # User 4 eligible for collaboration
        cl_ids = list(results[OnboardingEmail.EmailType.COLLABORATION].values_list("id", flat=True))
        assert user4.id in cl_ids

    def test_get_users_for_onboarding_sequence_skip_already_sent(self, ensure_billing_plans) -> None:
        """Test that already-sent emails are skipped."""
        user = User.objects.create_user(username="seqskip", email="seqskip@example.com")
        team = Team.objects.create(name="Skip Team", key="skip-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        # Mark quick_start as already sent
        email_record = OnboardingEmail.create_email(
            user=user, email_type=OnboardingEmail.EmailType.QUICK_START, subject="Quick Start"
        )
        email_record.mark_sent()

        results = OnboardingEmailService.get_users_for_onboarding_sequence()
        qs_ids = list(results[OnboardingEmail.EmailType.QUICK_START].values_list("id", flat=True))
        assert user.id not in qs_ids


@pytest.mark.django_db
class TestOnboardingSequenceTasks:
    """Test Dramatiq tasks for new onboarding sequence emails."""

    def test_send_quick_start_email_task_success(self) -> None:
        """Test quick start email task execution."""
        user = User.objects.create_user(username="qstask", email="qstask@example.com", password="test123")
        team = Team.objects.create(name="QS Task Team", key="qs-task-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        mail.outbox = []
        send_quick_start_email_task(user.id)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [user.email]

    def test_send_quick_start_email_task_user_not_found(self) -> None:
        """Test quick start task with non-existent user."""
        send_quick_start_email_task(99999)  # Should not raise

    def test_send_first_component_email_task_success(self) -> None:
        """Test first component email task execution."""
        user = User.objects.create_user(username="fctask", email="fctask@example.com", password="test123")
        team = Team.objects.create(name="FC Task Team", key="fc-task-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=4)
        status.save()

        mail.outbox = []
        send_first_component_email_task(user.id)

        assert len(mail.outbox) == 1

    def test_send_first_sbom_email_task_success(self) -> None:
        """Test first SBOM email task execution."""
        user = User.objects.create_user(username="fstask", email="fstask@example.com", password="test123")
        team = Team.objects.create(name="FS Task Team", key="fs-task-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.has_created_component = True
        status.first_component_created_at = timezone.now() - timedelta(days=8)
        status.created_at = timezone.now() - timedelta(days=10)
        status.save()

        mail.outbox = []
        send_first_sbom_email_task(user.id)

        assert len(mail.outbox) == 1

    def test_send_collaboration_email_task_success(self) -> None:
        """Test collaboration email task execution."""
        user = User.objects.create_user(username="cltask", email="cltask@example.com", password="test123")
        team = Team.objects.create(name="CL Task Team", key="cl-task-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=12)
        status.save()

        mail.outbox = []
        send_collaboration_email_task(user.id)

        assert len(mail.outbox) == 1

    @patch("sbomify.apps.onboarding.tasks.send_quick_start_email_task")
    @patch("sbomify.apps.onboarding.tasks.send_first_component_email_task")
    @patch("sbomify.apps.onboarding.tasks.send_first_sbom_email_task")
    @patch("sbomify.apps.onboarding.tasks.send_collaboration_email_task")
    def test_process_onboarding_sequence_batch_task(
        self,
        mock_collab: MagicMock,
        mock_sbom: MagicMock,
        mock_component: MagicMock,
        mock_quick: MagicMock,
        ensure_billing_plans,
    ) -> None:
        """Test batch processing of onboarding sequence emails."""
        # Create user eligible for quick_start
        user = User.objects.create_user(username="batch1", email="batch1@example.com")
        team = Team.objects.create(name="Batch Team", key="batch-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        mock_quick.send.return_value = MagicMock(message_id="test-id")
        mock_component.send.return_value = MagicMock(message_id="test-id")
        mock_sbom.send.return_value = MagicMock(message_id="test-id")
        mock_collab.send.return_value = MagicMock(message_id="test-id")

        process_onboarding_sequence_batch_task()

        # Quick start should be queued for eligible user
        assert mock_quick.send.call_count == 1


@pytest.mark.django_db
class TestOnboardingSequenceProgression:
    """Test the full onboarding email sequence progression."""

    def test_sequence_progression_over_time(self) -> None:
        """Test correct emails are eligible at correct days."""
        user = User.objects.create_user(username="prog1", email="prog1@example.com", password="test123")
        team = Team.objects.create(name="Prog Team", key="prog-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()

        # Day 0: nothing eligible yet
        assert not status.should_receive_quick_start(days_threshold=1)
        assert not status.should_receive_component_reminder(days_threshold=3)
        assert not status.should_receive_collaboration(days_threshold=10)

        # Day 1: quick start eligible
        status.created_at = timezone.now() - timedelta(days=1)
        status.save()
        assert status.should_receive_quick_start(days_threshold=1)
        assert not status.should_receive_component_reminder(days_threshold=3)

        # Day 3: first component eligible (no component created)
        status.created_at = timezone.now() - timedelta(days=3)
        status.save()
        assert status.should_receive_component_reminder(days_threshold=3)

        # Day 10: collaboration eligible (solo workspace)
        status.created_at = timezone.now() - timedelta(days=10)
        status.save()
        assert status.should_receive_collaboration(days_threshold=10)

    def test_skip_component_email_if_component_exists(self) -> None:
        """Test first component email skipped if component already created."""
        user = User.objects.create_user(username="skip1", email="skip1@example.com", password="test123")
        team = Team.objects.create(name="Skip Team 1", key="skip-team-1")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        Component.objects.create(name="skip-comp", team=team)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=5)
        status.save()

        # Component exists in workspace, so component reminder should be skipped
        assert not status.should_receive_component_reminder(days_threshold=3)

    def test_skip_sbom_email_if_sbom_exists(self) -> None:
        """Test first SBOM email skipped if SBOM already uploaded."""
        user = User.objects.create_user(username="skip2", email="skip2@example.com", password="test123")
        team = Team.objects.create(name="Skip Team 2", key="skip-team-2")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        component = Component.objects.create(name="skip-comp-2", team=team)
        SBOM.objects.create(name="skip-sbom", component=component)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_component_created()
        status.first_component_created_at = timezone.now() - timedelta(days=10)
        status.save()

        # SBOM exists, so SBOM reminder should be skipped
        assert not status.should_receive_sbom_reminder(days_threshold=7)

    def test_skip_collaboration_if_team_has_members(self) -> None:
        """Test collaboration email skipped if workspace has multiple members."""
        user = User.objects.create_user(username="skip3", email="skip3@example.com", password="test123")
        user2 = User.objects.create_user(username="skip3b", email="skip3b@example.com", password="test123")
        team = Team.objects.create(name="Skip Team 3", key="skip-team-3")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        Member.objects.create(user=user2, team=team, role="member")

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=15)
        status.save()

        assert not status.should_receive_collaboration(days_threshold=10)


@pytest.mark.django_db
class TestEdgeCasesAndErrorHandling:
    """Test edge cases, error handling, and race conditions."""

    def test_eligible_check_exception_returns_false(self) -> None:
        """T1: _send_onboarding_email returns False when eligible_check raises a non-DB error."""
        user = User.objects.create_user(username="ec1", email="ec1@example.com", password="test123")

        def bad_check():
            raise ValueError("bad eligibility check")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives"):
            result = OnboardingEmailService._send_onboarding_email(
                user,
                email_type=OnboardingEmail.EmailType.QUICK_START,
                template_name="quick_start",
                subject="Test",
                eligible_check=bad_check,
            )
        assert result is False
        # No email record should be created
        assert not OnboardingEmail.objects.filter(user=user, email_type=OnboardingEmail.EmailType.QUICK_START).exists()

    def test_eligible_check_operational_error_propagates(self) -> None:
        """T1b: _send_onboarding_email re-raises OperationalError from eligible_check."""
        from django.db import OperationalError

        user = User.objects.create_user(username="ec1b", email="ec1b@example.com", password="test123")

        def db_error_check():
            raise OperationalError("connection refused")

        with pytest.raises(OperationalError, match="connection refused"):
            OnboardingEmailService._send_onboarding_email(
                user,
                email_type=OnboardingEmail.EmailType.QUICK_START,
                template_name="quick_start",
                subject="Test",
                eligible_check=db_error_check,
            )

    def test_welcome_email_integrity_error_concurrent_sent(self) -> None:
        """T2: Welcome email returns True when IntegrityError race and concurrent record is SENT."""
        user = User.objects.create_user(username="ec2", email="ec2@example.com", password="test123")

        with (
            patch("sbomify.apps.onboarding.services.EmailMultiAlternatives"),
            patch.object(OnboardingEmail, "create_email", side_effect=IntegrityError("duplicate")),
        ):
            # Pre-create a SENT record to simulate concurrent worker
            OnboardingEmail.objects.create(
                user=user,
                email_type=OnboardingEmail.EmailType.WELCOME,
                subject="Welcome",
                status=OnboardingEmail.EmailStatus.SENT,
            )
            result = OnboardingEmailService.send_welcome_email(user)

        # Should return True because the email was already sent
        assert result is True

    def test_welcome_email_integrity_error_concurrent_pending(self) -> None:
        """T2b: Welcome email returns False when IntegrityError race and concurrent record is PENDING."""
        user = User.objects.create_user(username="ec2b", email="ec2b@example.com", password="test123")

        with (
            patch("sbomify.apps.onboarding.services.EmailMultiAlternatives"),
            patch.object(OnboardingEmail, "create_email", side_effect=IntegrityError("duplicate")),
        ):
            # Pre-create a PENDING record to simulate concurrent worker in-progress
            OnboardingEmail.objects.create(
                user=user,
                email_type=OnboardingEmail.EmailType.WELCOME,
                subject="Welcome",
                status=OnboardingEmail.EmailStatus.PENDING,
            )
            result = OnboardingEmailService.send_welcome_email(user)

        assert result is False

    def test_first_component_integrity_error_concurrent_sent(self) -> None:
        """T3: First component email returns True when race and concurrent record is SENT."""
        user = User.objects.create_user(username="ec3", email="ec3@example.com", password="test123")
        team = Team.objects.create(name="EC3 Team", key="ec3-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=5)
        status.save()

        def create_and_raise(**kwargs):
            """Simulate concurrent worker: create SENT record then raise IntegrityError."""
            OnboardingEmail.objects.create(
                user=user,
                email_type=OnboardingEmail.EmailType.FIRST_COMPONENT,
                subject="Component",
                status=OnboardingEmail.EmailStatus.SENT,
            )
            raise IntegrityError("duplicate")

        with (
            patch("sbomify.apps.onboarding.services.EmailMultiAlternatives"),
            patch.object(OnboardingEmail, "create_email", side_effect=create_and_raise),
        ):
            result = OnboardingEmailService.send_first_component_email(user)

        # Concurrent worker already sent → returns True
        assert result is True

    def test_first_component_retry_after_failure(self) -> None:
        """T4: FAILED record is deleted and retry succeeds (render-before-delete ordering)."""
        user = User.objects.create_user(username="ec4", email="ec4@example.com", password="test123")
        team = Team.objects.create(name="EC4 Team", key="ec4-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=5)
        status.save()

        # Create a FAILED record
        OnboardingEmail.objects.create(
            user=user,
            email_type=OnboardingEmail.EmailType.FIRST_COMPONENT,
            subject="Component",
            status=OnboardingEmail.EmailStatus.FAILED,
        )

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives"):
            result = OnboardingEmailService.send_first_component_email(user)

        assert result is True
        # FAILED record should be deleted, new SENT record should exist
        records = OnboardingEmail.objects.filter(user=user, email_type=OnboardingEmail.EmailType.FIRST_COMPONENT)
        assert records.count() == 1
        assert records.first().status == OnboardingEmail.EmailStatus.SENT

    def test_signal_status_creation_failure_prevents_email_queue(self) -> None:
        """T5: If OnboardingStatus creation fails, welcome email is not queued."""
        with (
            patch.object(
                type(OnboardingStatus.objects),
                "create",
                side_effect=Exception("DB error"),
            ),
            patch("sbomify.apps.onboarding.tasks.queue_welcome_email") as mock_queue,
        ):
            # Creating user triggers signal but status creation fails
            User.objects.create_user(username="ec5", email="ec5@example.com", password="test123")
            mock_queue.assert_not_called()

    def test_signal_email_queue_failure_preserves_status(self) -> None:
        """T5b: If welcome email queuing fails, OnboardingStatus is still created."""
        with patch(
            "sbomify.apps.onboarding.tasks.queue_welcome_email",
            side_effect=Exception("Queue error"),
        ):
            user = User.objects.create_user(username="ec5b", email="ec5b@example.com", password="test123")

        # OnboardingStatus should still exist
        assert OnboardingStatus.objects.filter(user=user).exists()

    def test_non_sbom_component_does_not_trigger_tracking(self) -> None:
        """T6: A non-SBOM component type does not trigger first component tracking."""
        user = User.objects.create_user(username="ec6", email="ec6@example.com", password="test123")
        team = Team.objects.create(name="EC6 Team", key="ec6-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        assert not status.has_created_component

        # Create a non-SBOM component (document type)
        Component.objects.create(
            name="Document Component",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
        )

        status.refresh_from_db()
        assert not status.has_created_component

    def test_batch_skips_user_with_no_onboarding_status(self) -> None:
        """T8: Batch methods skip users without OnboardingStatus records."""
        user = User.objects.create_user(username="ec8", email="ec8@example.com", password="test123")
        team = Team.objects.create(name="EC8 Team", key="ec8-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        # Delete the auto-created OnboardingStatus
        OnboardingStatus.objects.filter(user=user).delete()

        # Should not crash, just skip the user
        result = OnboardingEmailService.get_users_for_onboarding_sequence()
        for email_type, users in result.items():
            assert user.id not in [u.id for u in users]

    def test_batch_sequence_continues_after_user_error(self) -> None:
        """Batch processing continues even if one user causes an error."""
        user1 = User.objects.create_user(username="ec9a", email="ec9a@example.com", password="test123")
        user2 = User.objects.create_user(username="ec9b", email="ec9b@example.com", password="test123")
        team = Team.objects.create(name="EC9 Team", key="ec9-team")
        Member.objects.create(user=user1, team=team, role="owner", is_default_team=True)
        Member.objects.create(user=user2, team=team, role="owner", is_default_team=True)

        # Set up both users with welcome_email_sent and enough days
        status1 = OnboardingStatus.objects.get(user=user1)
        status1.mark_welcome_email_sent()
        status1.created_at = timezone.now() - timedelta(days=2)
        status1.save()

        status2 = OnboardingStatus.objects.get(user=user2)
        status2.mark_welcome_email_sent()
        status2.created_at = timezone.now() - timedelta(days=2)
        status2.save()

        # Selectively make should_receive_quick_start fail for user1
        original_method = OnboardingStatus.should_receive_quick_start

        def selective_fail(self, *args, **kwargs):
            if self.user_id == user1.id:
                raise RuntimeError("Simulated error")
            return original_method(self, *args, **kwargs)

        with patch.object(OnboardingStatus, "should_receive_quick_start", selective_fail):
            result = OnboardingEmailService.get_users_for_onboarding_sequence()

        # user2 should still be eligible for quick_start despite user1's error
        quick_start_ids = [u.id for u in result[OnboardingEmail.EmailType.QUICK_START]]
        assert user2.id in quick_start_ids


@pytest.mark.django_db
class TestTransientSendFailuresRetry:
    """A mail outage must not cost a user their email.

    The sending actors declare ``max_retries=3``, and that budget is only
    reachable if something raises. Every send path used to report a failure as
    a ``False`` return, so the actor saw a clean return, acknowledged the
    message, and nothing ever tried again — a welcome email lost to a brief
    unreachable mail host was lost permanently.
    """

    @staticmethod
    def _user(name: str) -> Any:
        user = User.objects.create_user(username=name, email=f"{name}@example.com", password="test123")
        team = Team.objects.create(name=f"{name} Team", key=f"{name}-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        return user

    def test_unreachable_mail_host_raises_so_the_actor_retries(self) -> None:
        """This is the failure Sentry recorded: OSError 113, no route to host."""
        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("transient")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = OSError(113, "No route to host")
            with pytest.raises(TransientEmailError):
                OnboardingEmailService.send_welcome_email(user)

        record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.WELCOME)
        assert record.status == OnboardingEmail.EmailStatus.FAILED

    def test_smtp_connect_failure_raises(self) -> None:
        import smtplib

        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("smtpdown")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPConnectError(421, "try later")
            with pytest.raises(TransientEmailError):
                OnboardingEmailService.send_welcome_email(user)

    def test_a_permanently_refused_recipient_does_not_retry(self) -> None:
        """550 is the server saying no, not "not now"."""
        import smtplib

        user = self._user("refused")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {"refused@example.com": (550, b"No such user here")}
            )
            assert OnboardingEmailService.send_welcome_email(user) is False

    def test_a_greylisted_recipient_does_retry(self) -> None:
        """450 is the server asking us to come back, so dropping it loses mail.

        smtplib raises ``SMTPRecipientsRefused`` for both, so the class alone
        cannot tell a greylist from a nonexistent mailbox — only the code can.
        """
        import smtplib

        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("greylisted")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {"greylisted@example.com": (450, b"Greylisted, try again later")}
            )
            with pytest.raises(TransientEmailError):
                OnboardingEmailService.send_welcome_email(user)

    def test_a_mailbox_over_quota_does_retry(self) -> None:
        import smtplib

        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("overquota")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {"full@example.com": (452, b"Insufficient system storage")}
            )
            with pytest.raises(TransientEmailError):
                OnboardingEmailService.send_welcome_email(user)

    def test_a_sender_refused_is_read_by_its_code(self) -> None:
        """421 is the server shutting the channel, 550 is a rejected sender."""
        import smtplib

        from sbomify.apps.onboarding.services import TransientEmailError

        transient_user = self._user("sender421")
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPSenderRefused(
                421, b"Service not available", "us@example.com"
            )
            with pytest.raises(TransientEmailError):
                OnboardingEmailService.send_welcome_email(transient_user)

        permanent_user = self._user("sender550")
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPSenderRefused(
                550, b"Sender rejected", "us@example.com"
            )
            assert OnboardingEmailService.send_welcome_email(permanent_user) is False

    def test_an_unsupported_extension_does_not_retry(self) -> None:
        """The server will not have learned it by the next attempt."""
        import smtplib

        user = self._user("unsupported")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPNotSupportedError("no SMTPUTF8")
            assert OnboardingEmailService.send_welcome_email(user) is False

    def test_a_permanent_response_error_does_not_burn_the_budget(self) -> None:
        """A 5xx the server answered will answer the same way four times.

        These are the ones a class check gets wrong in the expensive direction:
        both subclass SMTPResponseException and would otherwise fall through to
        the OSError transport rule and retry.
        """
        import smtplib

        over_quota = self._user("quota552")
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPDataError(552, b"Message size exceeds limit")
            assert OnboardingEmailService.send_welcome_email(over_quota) is False

        bad_credential = self._user("auth535")
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPAuthenticationError(
                535, b"authentication failed"
            )
            assert OnboardingEmailService.send_welcome_email(bad_credential) is False

    def test_a_temporary_response_error_still_retries(self) -> None:
        import smtplib

        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("data451")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPDataError(451, b"Local error, try again")
            with pytest.raises(TransientEmailError):
                OnboardingEmailService.send_welcome_email(user)

    def test_one_permanent_refusal_among_temporary_ones_does_not_retry(self) -> None:
        """A retry re-sends the whole message, so all-4xx is the rule, not any.

        With a mix, another attempt would redeliver to the greylisted recipient
        and be refused again by the one that does not exist.
        """
        import smtplib

        user = self._user("mixedrefusal")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {
                    "greylisted@example.com": (450, b"Greylisted, try again later"),
                    "gone@example.com": (550, b"No such user here"),
                }
            )
            assert OnboardingEmailService.send_welcome_email(user) is False

    def test_a_dropped_connection_retries(self) -> None:
        """No server answer at all, so there is no code to read — transport."""
        import smtplib

        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("disconnected")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPServerDisconnected("connection lost")
            with pytest.raises(TransientEmailError):
                OnboardingEmailService.send_welcome_email(user)

    def test_a_refused_address_is_remembered_and_not_re_sent(self) -> None:
        """The daily batch must not keep re-sending to a mailbox that is gone.

        A FAILED row is deleted and recreated on the next pass, which is right
        for a broken template and wrong for a 550: nothing we fix makes the
        address exist, and re-sending daily only earns bounces.
        """
        import smtplib

        user = self._user("refusedremembered")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {"gone@example.com": (550, b"No such user here")}
            )
            assert OnboardingEmailService.send_welcome_email(user) is False

        record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.WELCOME)
        assert record.status == OnboardingEmail.EmailStatus.UNDELIVERABLE

        # The next batch pass: the mailer must not be reached at all.
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            assert OnboardingEmailService.send_welcome_email(user) is False
            mock_email_cls.assert_not_called()

        assert OnboardingEmail.objects.filter(user=user, email_type=OnboardingEmail.EmailType.WELCOME).count() == 1

    def test_a_refused_address_is_remembered_on_the_sequence_emails_too(self) -> None:
        import smtplib

        user = self._user("seqrefused")
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {"gone@example.com": (550, b"No such user here")}
            )
            assert OnboardingEmailService.send_quick_start_email(user) is False

        record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.QUICK_START)
        assert record.status == OnboardingEmail.EmailStatus.UNDELIVERABLE

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            assert OnboardingEmailService.send_quick_start_email(user) is False
            mock_email_cls.assert_not_called()

    def test_a_corrected_address_is_tried_again(self) -> None:
        """A refusal is about an address, not about a user.

        The profile sync writes a new address from Keycloak, and a user can fix
        a typo. Suppressing on the user alone would silence onboarding forever
        for an address nobody ever refused.
        """
        import smtplib

        user = self._user("typo")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {user.email: (550, b"No such user here")}
            )
            assert OnboardingEmailService.send_welcome_email(user) is False

        record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.WELCOME)
        assert record.status == OnboardingEmail.EmailStatus.UNDELIVERABLE
        assert record.attempted_address == "typo@example.com"

        user.email = "corrected@example.com"
        user.save(update_fields=["email"])

        mail.outbox = []
        assert OnboardingEmailService.send_welcome_email(user) is True
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["corrected@example.com"]

    def test_an_address_recorded_before_this_field_still_suppresses(self) -> None:
        """A blank attempted_address is an older row, not a cleared one.

        Treating it as "no address recorded, so try again" would re-send to
        whatever refused it in the first place.
        """
        user = self._user("legacyrefusal")
        record = OnboardingEmail.create_email(
            user=user, email_type=OnboardingEmail.EmailType.WELCOME, subject="Welcome"
        )
        record.status = OnboardingEmail.EmailStatus.UNDELIVERABLE
        record.attempted_address = ""
        record.save(update_fields=["status", "attempted_address"])

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            assert OnboardingEmailService.send_welcome_email(user) is False
            mock_email_cls.assert_not_called()

    def test_a_fault_on_our_side_is_still_retried_by_a_later_pass(self) -> None:
        """Only the recipient's own refusal is remembered.

        A 552 over-size or a 535 bad credential is terminal for the attempt but
        ours to fix, and the address is fine. Marking those undeliverable would
        strand every user behind one misconfiguration with nothing to clear it.
        """
        import smtplib

        for name, error in (
            ("oursize", smtplib.SMTPDataError(552, b"Message size exceeds limit")),
            ("ourauth", smtplib.SMTPAuthenticationError(535, b"authentication failed")),
        ):
            user = self._user(name)
            with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
                mock_email_cls.return_value.send.side_effect = error
                assert OnboardingEmailService.send_welcome_email(user) is False

            record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.WELCOME)
            assert record.status == OnboardingEmail.EmailStatus.FAILED, name

            # The config is fixed; the next pass delivers.
            mail.outbox = []
            assert OnboardingEmailService.send_welcome_email(user) is True, name
            assert len(mail.outbox) == 1

    def test_a_refused_sender_does_not_strand_the_recipient(self) -> None:
        """Our envelope was wrong, not their address."""
        import smtplib

        user = self._user("senderrefused")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPSenderRefused(
                550, b"Sender rejected", "us@example.com"
            )
            assert OnboardingEmailService.send_welcome_email(user) is False

        record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.WELCOME)
        assert record.status == OnboardingEmail.EmailStatus.FAILED

    def test_an_abandoned_pending_row_is_reclaimed(self) -> None:
        """A worker that died between create_email() and the send strands a row.

        The unique constraint then makes every later attempt raise
        ``IntegrityError``, the handler reads that as a concurrent worker and
        answers ``False``, and the recovery sweep can never get the signup back.
        Nothing else clears it, because nothing else knows the worker is gone.
        """
        from sbomify.apps.onboarding.services import ABANDONED_PENDING_AFTER

        user = self._user("abandoned")
        stranded = OnboardingEmail.create_email(
            user=user, email_type=OnboardingEmail.EmailType.WELCOME, subject="Welcome"
        )
        assert stranded.status == OnboardingEmail.EmailStatus.PENDING
        OnboardingEmail.objects.filter(pk=stranded.pk).update(
            created_at=timezone.now() - ABANDONED_PENDING_AFTER - timedelta(minutes=1)
        )

        mail.outbox = []
        assert OnboardingEmailService.send_welcome_email(user) is True
        assert len(mail.outbox) == 1
        assert OnboardingEmail.objects.filter(user=user, email_type=OnboardingEmail.EmailType.WELCOME).count() == 1

    @pytest.mark.django_db(transaction=True)
    def test_a_live_pending_row_is_left_to_its_worker(self) -> None:
        """Inside the lease it is another worker's, not a leftover.

        ``transaction=True`` because the collision this exercises is a real
        ``IntegrityError``, and outside autocommit that leaves the test's own
        transaction unusable for the query the handler makes next.
        """
        user = self._user("liveworker")
        OnboardingEmail.create_email(user=user, email_type=OnboardingEmail.EmailType.WELCOME, subject="Welcome")

        mail.outbox = []
        assert OnboardingEmailService.send_welcome_email(user) is False
        assert mail.outbox == []

    def test_an_abandoned_pending_sequence_row_is_reclaimed_too(self) -> None:
        from sbomify.apps.onboarding.services import ABANDONED_PENDING_AFTER

        user = self._user("abandonedseq")
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        stranded = OnboardingEmail.create_email(
            user=user, email_type=OnboardingEmail.EmailType.QUICK_START, subject="Quick start"
        )
        OnboardingEmail.objects.filter(pk=stranded.pk).update(
            created_at=timezone.now() - ABANDONED_PENDING_AFTER - timedelta(minutes=1)
        )

        mail.outbox = []
        assert OnboardingEmailService.send_quick_start_email(user) is True
        assert len(mail.outbox) == 1

    def test_a_broken_template_is_reported_as_permanent(self) -> None:
        """Rendering happens before the send block, so it needs its own answer.

        Left to escape, the task re-raises it and dramatiq runs the same
        template against the same context three more times. A template is not a
        transport; waiting does not repair one.
        """
        from django.template import TemplateDoesNotExist

        user = self._user("brokentemplate")

        with patch(
            "sbomify.apps.onboarding.services.render_email_templates",
            side_effect=TemplateDoesNotExist("welcome.html"),
        ):
            assert OnboardingEmailService.send_welcome_email(user) is False

    def test_a_broken_template_does_not_raise_out_of_the_task(self) -> None:
        from django.template import TemplateDoesNotExist

        user = self._user("brokentemplatetask")

        with patch(
            "sbomify.apps.onboarding.services.render_email_templates",
            side_effect=TemplateDoesNotExist("welcome.html"),
        ):
            # No pytest.raises: an exception here is dramatiq being handed a
            # retry it cannot use.
            send_welcome_email_task(user.id)

    def test_a_template_error_does_not_retry(self) -> None:
        """Not a transport failure — retrying runs the same broken render."""
        user = self._user("template")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = ValueError("bad template")
            assert OnboardingEmailService.send_welcome_email(user) is False

    def test_the_sequence_emails_retry_too(self) -> None:
        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("seqtransient")
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = OSError(113, "No route to host")
            with pytest.raises(TransientEmailError):
                OnboardingEmailService.send_quick_start_email(user)

    def test_the_task_lets_a_transient_failure_out_so_dramatiq_sees_it(self) -> None:
        """The actor has to receive the exception, or the retry never happens."""
        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("tasktransient")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = OSError(113, "No route to host")
            with pytest.raises(TransientEmailError):
                send_welcome_email_task(user.id)

    def test_a_transient_failure_is_not_logged_at_error_on_every_attempt(self) -> None:
        """event_level=ERROR means an error line here is a Sentry issue.

        Four attempts would be four issues for one outage. The attempt that
        exhausts the retries still reports, via the unhandled exception.
        """
        from sbomify.apps.onboarding import tasks as onboarding_tasks
        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("quiettransient")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = OSError(113, "No route to host")
            with patch.object(onboarding_tasks, "logger", MagicMock()) as task_logger:
                with pytest.raises(TransientEmailError):
                    send_welcome_email_task(user.id)

        assert task_logger.error.call_count == 0
        assert task_logger.warning.call_count == 1

    def test_a_permanent_failure_still_reports_and_does_not_raise(self) -> None:
        """Unchanged behaviour: the service reports it, the actor stops.

        The error-level record — the one that becomes the Sentry issue — comes
        from the service, which is where the failure is understood. The task
        sees a ``False`` return, says so at warning level, and does not raise,
        because retrying a broken render just runs it again.
        """
        from sbomify.apps.onboarding import services as onboarding_services
        from sbomify.apps.onboarding import tasks as onboarding_tasks

        user = self._user("permanentloud")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = ValueError("bad template")
            with (
                patch.object(onboarding_services, "logger", MagicMock()) as service_logger,
                patch.object(onboarding_tasks, "logger", MagicMock()) as task_logger,
            ):
                send_welcome_email_task(user.id)

        assert service_logger.error.call_count == 1
        assert task_logger.error.call_count == 0
        assert task_logger.warning.call_count == 1

    def test_a_retry_after_a_transient_failure_delivers(self) -> None:
        """The FAILED record must not block the attempt that succeeds."""
        from sbomify.apps.onboarding.services import TransientEmailError

        user = self._user("eventually")

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = OSError(113, "No route to host")
            with pytest.raises(TransientEmailError):
                OnboardingEmailService.send_welcome_email(user)

        mail.outbox = []
        assert OnboardingEmailService.send_welcome_email(user) is True
        assert len(mail.outbox) == 1
        record = OnboardingEmail.objects.get(user=user, email_type=OnboardingEmail.EmailType.WELCOME)
        assert record.status == OnboardingEmail.EmailStatus.SENT


@pytest.mark.django_db
class TestWelcomeRecoverySweep:
    """The welcome email's only second chance.

    It is queued once, by a signal on user creation, so a send that failed had
    nothing else to pick it up: a broken template or an exhausted retry budget
    cost the message outright rather than delaying it.
    """

    @staticmethod
    def _owner(name: str, *, welcome_sent: bool, age_days: int = 0, owner: bool = True) -> Any:
        user = User.objects.create_user(username=name, email=f"{name}@example.com", password="test123")
        if owner:
            team = Team.objects.create(name=f"{name} Team", key=f"{name}-team")
            Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        status = OnboardingStatus.objects.get_or_create(user=user)[0]
        if welcome_sent:
            status.mark_welcome_email_sent()
        if age_days:
            # The account's own age is what the sweep measures.
            User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=age_days))
        return user

    @staticmethod
    def _run_sweep() -> list[int]:
        from sbomify.apps.onboarding.tasks import requeue_missed_welcome_emails_task, send_welcome_email_task

        with patch.object(send_welcome_email_task, "send_with_options") as sender:
            requeue_missed_welcome_emails_task()
        return [call.kwargs["args"][0] for call in sender.call_args_list]

    def test_a_recent_signup_without_a_welcome_email_is_requeued(self) -> None:
        user = self._owner("missedwelcome", welcome_sent=False)
        assert user.id in self._run_sweep()

    def test_a_user_who_got_one_is_left_alone(self) -> None:
        user = self._owner("gotwelcome", welcome_sent=True)
        assert user.id not in self._run_sweep()

    def test_the_sweep_does_not_reach_back_past_its_window(self) -> None:
        """Without the bound, the first run mails every account that predates
        the onboarding sequence. The welcome email goes out within seconds of
        signup, so anything that will fail has failed long before the cutoff.
        """
        from sbomify.apps.onboarding.tasks import WELCOME_RECOVERY_WINDOW_DAYS

        user = self._owner("ancient", welcome_sent=False, age_days=WELCOME_RECOVERY_WINDOW_DAYS + 1)
        assert user.id not in self._run_sweep()

    def test_an_old_account_with_a_new_status_row_is_not_swept(self) -> None:
        """The window is the account's age, not its status row's.

        A status row is created by ``get_or_create`` from the component and
        SBOM tracking paths, so a long-lived user can acquire a brand-new one
        this week. Keying the cutoff to that row would mail someone who signed
        up years ago.
        """
        from sbomify.apps.onboarding.tasks import WELCOME_RECOVERY_WINDOW_DAYS

        user = self._owner("oldaccount", welcome_sent=False, age_days=WELCOME_RECOVERY_WINDOW_DAYS + 400)
        status = OnboardingStatus.objects.get(user=user)
        OnboardingStatus.objects.filter(pk=status.pk).update(created_at=timezone.now())

        assert user.id not in self._run_sweep()

    def test_a_closed_account_is_not_swept(self) -> None:
        """An account can be deleted between the failed send and the sweep.

        Same liveness pair the rest of the codebase uses for "is this account
        still a thing": ``is_active`` and ``deleted_at``.
        """
        deactivated = self._owner("deactivated", welcome_sent=False)
        User.objects.filter(pk=deactivated.pk).update(is_active=False)

        soft_deleted = self._owner("softdeleted", welcome_sent=False)
        User.objects.filter(pk=soft_deleted.pk).update(deleted_at=timezone.now())

        swept = self._run_sweep()
        assert deactivated.id not in swept
        assert soft_deleted.id not in swept

    def test_the_send_itself_refuses_a_closed_account(self) -> None:
        """The query filter is an optimisation; this is the guarantee.

        A send queued before a deletion runs after it, so the check has to be
        at the send rather than only where something decided to send.
        """
        user = self._owner("closedatsend", welcome_sent=False)
        User.objects.filter(pk=user.pk).update(is_active=False)
        user.refresh_from_db()

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            assert OnboardingEmailService.send_welcome_email(user) is False
            mock_email_cls.assert_not_called()

    def test_a_refused_address_is_not_re_queued_daily(self) -> None:
        """welcome_email_sent stays false forever after a refusal.

        The service would refuse each attempt anyway, but only after a task had
        been queued and its template rendered — every day, for an address that
        is not going to start working.
        """
        import smtplib

        user = self._owner("refuseddaily", welcome_sent=False)

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {user.email: (550, b"No such user here")}
            )
            assert OnboardingEmailService.send_welcome_email(user) is False

        assert user.id not in self._run_sweep()

    def test_a_refusal_of_an_old_address_does_not_block_the_sweep(self) -> None:
        """The exclusion has to track the address, like the send guard does."""
        import smtplib

        user = self._owner("refusedthenfixed", welcome_sent=False)

        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {user.email: (550, b"No such user here")}
            )
            assert OnboardingEmailService.send_welcome_email(user) is False

        User.objects.filter(pk=user.pk).update(email="fixed@example.com")
        assert user.id in self._run_sweep()

    def test_a_half_written_success_is_repaired_and_stops_being_swept(self) -> None:
        """The send writes the row, then the flag. A crash between them strands both.

        The sweep keys on the flag, so it would re-queue this user daily; the
        send's own SENT fast path would return early each time without ever
        fixing it. The drip gates on the same flag, so the whole sequence stays
        blocked behind an email that did go out.
        """
        user = self._owner("halfwritten", welcome_sent=False)
        OnboardingEmail.objects.create(
            user=user,
            email_type=OnboardingEmail.EmailType.WELCOME,
            subject="Welcome",
            status=OnboardingEmail.EmailStatus.SENT,
        )
        assert user.id in self._run_sweep(), "the sweep should pick it up once"

        mail.outbox = []
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            assert OnboardingEmailService.send_welcome_email(user) is True
            mock_email_cls.assert_not_called()
        assert mail.outbox == [], "the email already went out; it must not go out twice"

        status = OnboardingStatus.objects.get(user=user)
        assert status.welcome_email_sent is True
        assert user.id not in self._run_sweep(), "and not be picked up again"

    def test_a_half_written_success_is_repaired_even_when_the_template_is_broken(self) -> None:
        """The repair must not sit behind the render.

        This is the two failures compounding: a worker died after writing the
        row and before the flag, and the template is broken when the recovery
        task runs. Rendering first meant returning before the repair, so the
        sweep kept re-queueing a delivered email and the drip stayed blocked.
        """
        from django.template import TemplateDoesNotExist

        user = self._owner("halfwrittenbroken", welcome_sent=False)
        OnboardingEmail.objects.create(
            user=user,
            email_type=OnboardingEmail.EmailType.WELCOME,
            subject="Welcome",
            status=OnboardingEmail.EmailStatus.SENT,
        )

        with patch(
            "sbomify.apps.onboarding.services.render_email_templates",
            side_effect=TemplateDoesNotExist("welcome.html"),
        ):
            assert OnboardingEmailService.send_welcome_email(user) is True

        assert OnboardingStatus.objects.get(user=user).welcome_email_sent is True
        assert user.id not in self._run_sweep()

    def test_a_refused_address_is_not_rendered_for(self) -> None:
        """Nothing is rendered for a send that was never going to happen."""
        import smtplib

        user = self._owner("norenderrefused", welcome_sent=False)
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {user.email: (550, b"No such user here")}
            )
            assert OnboardingEmailService.send_welcome_email(user) is False

        with patch("sbomify.apps.onboarding.services.render_email_templates") as render:
            assert OnboardingEmailService.send_welcome_email(user) is False
            render.assert_not_called()

    def test_a_user_with_no_onboarding_status_is_swept(self) -> None:
        """The signal that creates the status row is the one that queues the email.

        So a user with no row is not an edge case to skip, it is the case where
        the welcome is most certainly missing. A query starting at the status
        table cannot see them at all.
        """
        user = User.objects.create_user(username="nostatus", email="nostatus@example.com", password="test123")
        OnboardingStatus.objects.filter(user=user).delete()
        assert not OnboardingStatus.objects.filter(user=user).exists()

        assert user.id in self._run_sweep()

    def test_a_user_with_no_address_yet_is_deferred_not_retired(self) -> None:
        """An empty address must not count as a delivered welcome.

        ``to=[""]`` is a one-element recipient list, so the send reports
        success and the flag gets set — retiring the user from this sweep for
        an email that went nowhere. They stay eligible until a profile sync
        supplies an address, and are picked up on the next pass.
        """
        user = self._owner("noaddress", welcome_sent=False)
        User.objects.filter(pk=user.pk).update(email="")
        user.refresh_from_db()

        mail.outbox = []
        assert OnboardingEmailService.send_welcome_email(user) is False
        assert mail.outbox == []
        assert OnboardingStatus.objects.get(user=user).welcome_email_sent is False
        assert user.id not in self._run_sweep()

        User.objects.filter(pk=user.pk).update(email="arrived@example.com")
        assert user.id in self._run_sweep()

    def test_a_synthetic_bot_is_not_swept(self) -> None:
        """Driving from users brings bot identities into range; they stay out.

        ``_is_mailable`` refuses them at the send, but only after a task has
        been queued and a template rendered for an address at a domain that
        does not resolve.
        """
        from sbomify.apps.oidc.services import BOT_EMAIL_DOMAIN, BOT_USERNAME_PREFIX

        by_username = User.objects.create_user(
            username=f"{BOT_USERNAME_PREFIX}abc", email="bot1@example.com", password="test123"
        )
        by_domain = User.objects.create_user(
            username="looks-human", email=f"bot2@{BOT_EMAIL_DOMAIN}", password="test123"
        )

        swept = self._run_sweep()
        assert by_username.id not in swept
        assert by_domain.id not in swept

    def test_a_signup_who_is_not_a_workspace_owner_is_still_swept(self) -> None:
        """The signal queues a welcome for every human user, not just owners.

        An owner-only sweep would leave a failed send lost for exactly the
        accounts that are not primary owners — an invitee, or someone whose
        workspace setup has not completed.
        """
        user = self._owner("notanowner", welcome_sent=False, owner=False)
        assert user.id in self._run_sweep()

    def test_a_drip_opt_out_does_not_suppress_the_welcome_email(self) -> None:
        """The opt-out covers the scheduled sequence, not this.

        The welcome email confirms an account the user just created, so it is
        transactional: ``send_welcome_email`` does not check the flag, and the
        model says so where the field is declared. Filtering on it here would
        suppress a welcome that failed before the opt-out, permanently.
        """
        user = self._owner("optedout", welcome_sent=False)
        status = OnboardingStatus.objects.get(user=user)
        status.unsubscribe_from_drip()
        assert user.id in self._run_sweep()

    def test_a_broken_template_is_recoverable_once_it_is_fixed(self) -> None:
        """The whole point: the render failure is no longer the end of it."""
        from django.template import TemplateDoesNotExist

        user = self._owner("templatebroken", welcome_sent=False)

        with patch(
            "sbomify.apps.onboarding.services.render_email_templates",
            side_effect=TemplateDoesNotExist("welcome.html"),
        ):
            assert OnboardingEmailService.send_welcome_email(user) is False

        assert user.id in self._run_sweep()

        mail.outbox = []
        assert OnboardingEmailService.send_welcome_email(user) is True
        assert len(mail.outbox) == 1


@pytest.mark.django_db
class TestRefusedAddressesLeaveTheBatch:
    """A settled refusal should stop costing a render every day.

    The send path refuses these anyway, but only once a task has been queued,
    its eligibility recomputed and its template rendered.
    """

    @staticmethod
    def _eligible_quick_start(user: Any) -> bool:
        eligible = OnboardingEmailService.get_users_for_onboarding_sequence()
        return user.id in [u.id for u in eligible[OnboardingEmail.EmailType.QUICK_START]]

    def _user_due_for_quick_start(self, name: str) -> Any:
        user = User.objects.create_user(username=name, email=f"{name}@example.com", password="test123")
        team = Team.objects.create(name=f"{name} Team", key=f"{name}-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=2)
        status.save()
        OnboardingStatus.objects.filter(pk=status.pk).update(created_at=timezone.now() - timedelta(days=2))
        return user

    def test_a_due_user_is_eligible(self) -> None:
        user = self._user_due_for_quick_start("duequick")
        assert self._eligible_quick_start(user)

    def test_a_refused_address_drops_out(self) -> None:
        import smtplib

        user = self._user_due_for_quick_start("refusedquick")
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {user.email: (550, b"No such user here")}
            )
            assert OnboardingEmailService.send_quick_start_email(user) is False

        assert not self._eligible_quick_start(user)

    def test_a_corrected_address_comes_back(self) -> None:
        import smtplib

        user = self._user_due_for_quick_start("fixedquick")
        with patch("sbomify.apps.onboarding.services.EmailMultiAlternatives") as mock_email_cls:
            mock_email_cls.return_value.send.side_effect = smtplib.SMTPRecipientsRefused(
                {user.email: (550, b"No such user here")}
            )
            assert OnboardingEmailService.send_quick_start_email(user) is False

        User.objects.filter(pk=user.pk).update(email="fixedquick2@example.com")
        assert self._eligible_quick_start(user)
