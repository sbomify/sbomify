"""
Onboarding email services.
"""

from django.conf import settings
from django.core.mail import send_mail

from sbomify.logging import getLogger

from ..models import OnboardingEmail, OnboardingStatus
from ..utils import get_email_context, render_email_templates

logger = getLogger(__name__)


class OnboardingEmailService:
    """Service for sending onboarding emails."""

    @staticmethod
    def send_welcome_email(user) -> bool:
        """
        Send welcome email to a new user.

        Args:
            user: User instance

        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            # Check if welcome email already sent
            onboarding_status, _ = OnboardingStatus.objects.get_or_create(user=user)
            if onboarding_status.welcome_email_sent:
                logger.info(f"Welcome email already sent to {user.email}")
                return True

            # Prepare email context
            context = get_email_context(user)

            # Render email templates
            html_content, plain_text_content = render_email_templates("welcome", context)

            # Create email record
            email_record = OnboardingEmail.create_email(
                user=user,
                email_type=OnboardingEmail.EmailType.WELCOME,
                subject="Welcome to sbomify - Let's Get Started!",
            )

            try:
                # Send email
                send_mail(
                    subject=email_record.subject,
                    message=plain_text_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    html_message=html_content,
                    fail_silently=False,
                )

                # Mark as sent
                email_record.mark_sent()
                onboarding_status.mark_welcome_email_sent()

                logger.info(f"Welcome email sent successfully to {user.email}")
                return True

            except Exception as e:
                error_msg = f"Failed to send welcome email: {str(e)}"
                email_record.mark_failed(error_msg)
                logger.error(f"Failed to send welcome email to {user.email}: {e}")
                return False

        except Exception as e:
            logger.error(f"Error in send_welcome_email for {user.email}: {e}")
            return False

    @staticmethod
    def send_first_component_sbom_email(user) -> bool:
        """
        Send first component & SBOM reminder email.

        This email adapts based on the user's progress:
        - If no component created: Focus on component creation
        - If component created but no SBOM: Focus on SBOM upload

        Args:
            user: User instance

        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            # Check if user should receive this email
            onboarding_status = OnboardingStatus.objects.filter(user=user).first()
            if not onboarding_status:
                logger.info(f"No onboarding status found for {user.email}")
                return False

            # Determine if user needs component or SBOM reminder
            needs_component = onboarding_status.should_receive_component_reminder()
            needs_sbom = onboarding_status.should_receive_sbom_reminder()

            if not needs_component and not needs_sbom:
                logger.info(f"First component/SBOM reminder not needed for {user.email}")
                return False

            # Check if email already sent
            existing_email = OnboardingEmail.objects.filter(
                user=user, email_type=OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM
            ).first()
            if existing_email:
                logger.info(f"First component/SBOM reminder already sent to {user.email}")
                return True

            # Prepare email context with progress information
            context = get_email_context(
                user,
                has_created_component=onboarding_status.has_created_component,
                needs_component=needs_component,
                needs_sbom=needs_sbom,
            )

            # Render email templates
            html_content, plain_text_content = render_email_templates("first_component_sbom", context)

            # Determine subject based on user's progress
            if needs_component:
                subject = "Ready to Create Your First Component? - sbomify"
            else:
                subject = "Time to Upload Your First SBOM! - sbomify"

            # Create email record
            email_record = OnboardingEmail.create_email(
                user=user, email_type=OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM, subject=subject
            )

            try:
                # Send email
                send_mail(
                    subject=email_record.subject,
                    message=plain_text_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    html_message=html_content,
                    fail_silently=False,
                )

                # Mark as sent
                email_record.mark_sent()

                logger.info(f"First component/SBOM reminder email sent successfully to {user.email}")
                return True

            except Exception as e:
                error_msg = f"Failed to send first component/SBOM reminder email: {str(e)}"
                email_record.mark_failed(error_msg)
                logger.error(f"Failed to send first component/SBOM reminder email to {user.email}: {e}")
                return False

        except Exception as e:
            logger.error(f"Error in send_first_component_sbom_email for {user.email}: {e}")
            return False

    @staticmethod
    def get_users_for_first_component_sbom_reminder():
        """
        Get workspace owners who should receive first component/SBOM reminders.

        This consolidates both component and SBOM reminder logic:
        - Component reminder: PRIMARY workspace owners with no components (3+ days after signup)
        - SBOM reminder: PRIMARY workspace owners with components but no SBOMs (7+ days after component)

        Returns:
            QuerySet of User objects (workspace owners only)
        """
        from django.contrib.auth import get_user_model

        from sbomify.apps.teams.models import Member

        User = get_user_model()
        eligible_users = []

        # Get all primary workspace owners
        primary_owners = Member.objects.filter(
            role="owner",
            is_default_team=True,  # This is their primary/default workspace
        ).select_related("user", "team")

        for member in primary_owners:
            try:
                status = OnboardingStatus.objects.get(user=member.user)

                # Check if they need component reminder
                if status.welcome_email_sent and status.should_receive_component_reminder(days_threshold=3):
                    eligible_users.append(member.user.id)
                    continue

                # Check if they need SBOM reminder
                if status.has_created_component and status.should_receive_sbom_reminder(days_threshold=7):
                    eligible_users.append(member.user.id)
                    continue

            except OnboardingStatus.DoesNotExist:
                continue

        # Filter out users who already received this email
        users_already_sent = OnboardingEmail.objects.filter(
            email_type=OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM
        ).values_list("user_id", flat=True)

        eligible_users = [uid for uid in eligible_users if uid not in users_already_sent]

        return User.objects.filter(id__in=eligible_users)
