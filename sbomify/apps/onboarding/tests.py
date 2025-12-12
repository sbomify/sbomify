"""
Tests for onboarding functionality using pytest and existing fixtures.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from sbomify.apps.core.models import Component
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Member, Team

from .models import OnboardingEmail, OnboardingStatus
from .services import OnboardingEmailService
from .tasks import (
    process_first_component_sbom_reminders_batch_task,
    queue_welcome_email,
    send_first_component_sbom_email_task,
    send_welcome_email_task,
)
from .utils import get_email_context, html_to_plain_text, render_email_templates

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
        test_user = User.objects.create_user(
            username="sbomtest", email="sbomtest@example.com", password="testpass123"
        )
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
        test_user = User.objects.create_user(
            username="uniquetest", email="unique@example.com", password="testpass123"
        )

        OnboardingEmail.create_email(user=test_user, email_type=OnboardingEmail.EmailType.WELCOME, subject="Welcome!")

        # Should not be able to create another welcome email for same user
        with pytest.raises(Exception):  # IntegrityError
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

        email_record = OnboardingEmail.objects.get(
            user=sample_user, email_type=OnboardingEmail.EmailType.WELCOME
        )
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
        email_record = OnboardingEmail.objects.get(
            user=sample_user, email_type=OnboardingEmail.EmailType.WELCOME
        )
        assert email_record.status == OnboardingEmail.EmailStatus.FAILED
        assert "SMTP Error" in email_record.error_message

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
        mock_task.send.return_value = MagicMock(message_id="test-message-id")

        message_id = queue_welcome_email(sample_user)

        assert message_id == "test-message-id"
        mock_task.send.assert_called_once_with(sample_user.id)


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