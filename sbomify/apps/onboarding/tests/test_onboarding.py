"""
Tests for onboarding functionality using pytest and existing fixtures.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError
from django.utils import timezone

from sbomify.apps.core.models import Component
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member, Team

from sbomify.apps.onboarding.models import OnboardingEmail, OnboardingStatus
from sbomify.apps.onboarding.services import OnboardingEmailService
from sbomify.apps.onboarding.tasks import (
    process_first_component_sbom_reminders_batch_task,
    process_onboarding_sequence_batch_task,
    queue_welcome_email,
    send_collaboration_email_task,
    send_first_component_email_task,
    send_first_component_sbom_email_task,
    send_first_sbom_email_task,
    send_quick_start_email_task,
    send_welcome_email_task,
)
from sbomify.apps.onboarding.utils import get_email_context, html_to_plain_text, render_email_templates

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

    def test_send_first_component_sbom_email_component_focus(self) -> None:
        """Test first component/SBOM email with component focus."""
        # Create fresh user/team to avoid fixture conflicts
        test_user = User.objects.create_user(username="comptest", email="comptest@example.com", password="test123")
        test_team = Team.objects.create(name="Test Team", key="test-team")
        Member.objects.create(user=test_user, team=test_team, role="owner", is_default_team=True)

        # Set up conditions for component reminder
        onboarding_status = OnboardingStatus.objects.get(user=test_user)
        onboarding_status.mark_welcome_email_sent()

        # Set creation time to 4 days ago
        past_time = timezone.now() - timedelta(days=4)
        onboarding_status.created_at = past_time
        onboarding_status.save()

        mail.outbox = []

        result = OnboardingEmailService.send_first_component_sbom_email(test_user)

        assert result is True
        assert len(mail.outbox) == 1

        email = mail.outbox[0]
        assert "component" in email.subject.lower()

    def test_send_first_component_sbom_email_sbom_focus(self) -> None:
        """Test first component/SBOM email with SBOM focus."""
        # Create fresh user/team to avoid fixture conflicts
        test_user = User.objects.create_user(username="sbomtest", email="sbomtest@example.com", password="test123")
        test_team = Team.objects.create(name="SBOM Team", key="sbom-team")
        Member.objects.create(user=test_user, team=test_team, role="owner", is_default_team=True)

        # Create component and set up conditions for SBOM reminder
        Component.objects.create(name="test-component", team=test_team)
        onboarding_status = OnboardingStatus.objects.get(user=test_user)
        onboarding_status.mark_component_created()

        # Set component creation time to 8 days ago
        past_time = timezone.now() - timedelta(days=8)
        onboarding_status.first_component_created_at = past_time
        onboarding_status.save()

        mail.outbox = []

        result = OnboardingEmailService.send_first_component_sbom_email(test_user)

        assert result is True
        assert len(mail.outbox) == 1

        email = mail.outbox[0]
        assert "sbom" in email.subject.lower()

    def test_send_first_component_sbom_email_not_eligible(self, sample_user) -> None:
        """Test first component/SBOM email not sent if user not eligible."""
        # User just signed up, not eligible yet (no team membership for non-fixture user)
        test_user = User.objects.create_user(username="noteligt", email="noteligt@example.com", password="test123")

        mail.outbox = []

        result = OnboardingEmailService.send_first_component_sbom_email(test_user)

        assert result is False
        assert len(mail.outbox) == 0

    @patch("sbomify.apps.onboarding.services.send_mail")
    def test_send_email_failure_handling(self, mock_send_mail: MagicMock, sample_user) -> None:
        """Test email sending failure handling."""
        mock_send_mail.side_effect = Exception("SMTP Error")

        result = OnboardingEmailService.send_welcome_email(sample_user)

        assert result is False

        # Check that failure is recorded
        email_record = OnboardingEmail.objects.get(user=sample_user, email_type=OnboardingEmail.EmailType.WELCOME)
        assert email_record.status == OnboardingEmail.EmailStatus.FAILED
        assert "SMTP send failure: Exception" in email_record.error_message

    def test_get_users_for_first_component_sbom_reminder(self, ensure_billing_plans) -> None:
        """Test getting users eligible for first component/SBOM reminder."""
        # Create multiple users with different statuses
        user1 = User.objects.create_user(username="user1", email="user1@example.com")
        user2 = User.objects.create_user(username="user2", email="user2@example.com")
        user3 = User.objects.create_user(username="user3", email="user3@example.com")

        # Create teams
        team1 = Team.objects.create(name="Team 1", key="team-1")
        team2 = Team.objects.create(name="Team 2", key="team-2")
        team3 = Team.objects.create(name="Team 3", key="team-3")

        # User1: Eligible for component reminder (welcome sent, 4 days ago, no component)
        Member.objects.create(user=user1, team=team1, role="owner", is_default_team=True)
        status1 = OnboardingStatus.objects.get(user=user1)
        status1.mark_welcome_email_sent()
        status1.created_at = timezone.now() - timedelta(days=4)
        status1.save()

        # User2: Eligible for SBOM reminder (component created 8 days ago, no SBOM)
        Member.objects.create(user=user2, team=team2, role="owner", is_default_team=True)
        Component.objects.create(name="component-2", team=team2)
        status2 = OnboardingStatus.objects.get(user=user2)
        status2.mark_component_created()
        status2.first_component_created_at = timezone.now() - timedelta(days=8)
        status2.save()

        # User3: Not eligible (workspace already has SBOM)
        Member.objects.create(user=user3, team=team3, role="owner", is_default_team=True)
        component3 = Component.objects.create(name="component-3", team=team3)
        SBOM.objects.create(name="sbom-3", component=component3)
        status3 = OnboardingStatus.objects.get(user=user3)
        status3.mark_component_created()
        status3.mark_sbom_uploaded()
        status3.first_component_created_at = timezone.now() - timedelta(days=8)
        status3.save()

        eligible_users = OnboardingEmailService.get_users_for_first_component_sbom_reminder()

        assert eligible_users.count() == 2  # Both user1 and user2 are eligible
        assert user1 in eligible_users
        assert user2 in eligible_users
        assert user3 not in eligible_users


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

    def test_send_first_component_sbom_email_task_success(self) -> None:
        """Test first component/SBOM email task execution."""
        # Create fresh user/team for component reminder
        test_user = User.objects.create_user(username="tasktest", email="tasktest@example.com", password="test123")
        test_team = Team.objects.create(name="Task Team", key="task-team")
        Member.objects.create(user=test_user, team=test_team, role="owner", is_default_team=True)

        # Set up conditions for component reminder
        onboarding_status = OnboardingStatus.objects.get(user=test_user)
        onboarding_status.mark_welcome_email_sent()

        # Set creation time to 4 days ago
        past_time = timezone.now() - timedelta(days=4)
        onboarding_status.created_at = past_time
        onboarding_status.save()

        mail.outbox = []

        send_first_component_sbom_email_task(test_user.id)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [test_user.email]

    def test_send_first_component_sbom_email_task_not_eligible(self, sample_user) -> None:
        """Test first component/SBOM email task when user not eligible."""
        # User just signed up, not eligible yet (no team membership)
        test_user = User.objects.create_user(username="notelig", email="notelig@example.com", password="test123")

        mail.outbox = []

        send_first_component_sbom_email_task(test_user.id)

        # No email sent when user is not eligible
        assert len(mail.outbox) == 0

    @patch("sbomify.apps.onboarding.tasks.send_first_component_sbom_email_task")
    def test_process_first_component_sbom_reminders_batch_task(
        self, mock_task: MagicMock, ensure_billing_plans
    ) -> None:
        """Test batch processing of first component/SBOM reminders."""
        # Create multiple users with different statuses
        user1 = User.objects.create_user(username="user1", email="user1@example.com")
        user2 = User.objects.create_user(username="user2", email="user2@example.com")

        # Create teams
        team1 = Team.objects.create(name="Team 1", key="team-1")
        team2 = Team.objects.create(name="Team 2", key="team-2")

        # User1: Eligible for component reminder
        Member.objects.create(user=user1, team=team1, role="owner", is_default_team=True)
        status1 = OnboardingStatus.objects.get(user=user1)
        status1.mark_welcome_email_sent()
        status1.created_at = timezone.now() - timedelta(days=4)
        status1.save()

        # User2: Eligible for SBOM reminder
        Member.objects.create(user=user2, team=team2, role="owner", is_default_team=True)
        Component.objects.create(name="component-2", team=team2)
        status2 = OnboardingStatus.objects.get(user=user2)
        status2.mark_component_created()
        status2.first_component_created_at = timezone.now() - timedelta(days=8)
        status2.save()

        # Mock the individual task sending to avoid actual task queue
        mock_task.send.return_value = MagicMock(message_id="test-task-id")

        process_first_component_sbom_reminders_batch_task()

        # Verify the task was called for both eligible users
        assert mock_task.send.call_count == 2

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

        # Send first component/SBOM reminder (component focus)
        result = OnboardingEmailService.send_first_component_sbom_email(test_user)
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

    @patch("sbomify.apps.onboarding.services.send_mail")
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

        # First attempt: simulate SMTP failure
        with patch("sbomify.apps.onboarding.services.send_mail", side_effect=Exception("SMTP Error")):
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

        with patch("sbomify.apps.onboarding.services.send_mail"):
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
            patch("sbomify.apps.onboarding.services.send_mail"),
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
            patch("sbomify.apps.onboarding.services.send_mail"),
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

    def test_first_component_sbom_integrity_error_concurrent_sent(self) -> None:
        """T3: First component/SBOM email returns True when race and concurrent record is SENT."""
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
                email_type=OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM,
                subject="Component",
                status=OnboardingEmail.EmailStatus.SENT,
            )
            raise IntegrityError("duplicate")

        with (
            patch("sbomify.apps.onboarding.services.send_mail"),
            patch.object(OnboardingEmail, "create_email", side_effect=create_and_raise),
        ):
            result = OnboardingEmailService.send_first_component_sbom_email(user)

        # Concurrent worker already sent → returns True
        assert result is True

    def test_first_component_sbom_retry_after_failure(self) -> None:
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
            email_type=OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM,
            subject="Component",
            status=OnboardingEmail.EmailStatus.FAILED,
        )

        with patch("sbomify.apps.onboarding.services.send_mail"):
            result = OnboardingEmailService.send_first_component_sbom_email(user)

        assert result is True
        # FAILED record should be deleted, new SENT record should exist
        records = OnboardingEmail.objects.filter(user=user, email_type=OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM)
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

    def test_cross_reference_guard_excludes_users_with_new_sequence_emails(self) -> None:
        """T7: get_users_for_first_component_sbom_reminder excludes users with newer sequence emails."""
        user = User.objects.create_user(username="ec7", email="ec7@example.com", password="test123")
        team = Team.objects.create(name="EC7 Team", key="ec7-team")
        Member.objects.create(user=user, team=team, role="owner", is_default_team=True)

        status = OnboardingStatus.objects.get(user=user)
        status.mark_welcome_email_sent()
        status.created_at = timezone.now() - timedelta(days=5)
        status.save()

        # User already received FIRST_COMPONENT from the new sequence
        OnboardingEmail.objects.create(
            user=user,
            email_type=OnboardingEmail.EmailType.FIRST_COMPONENT,
            subject="First Component",
            status=OnboardingEmail.EmailStatus.SENT,
        )

        eligible = OnboardingEmailService.get_users_for_first_component_sbom_reminder()
        assert user not in eligible

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
