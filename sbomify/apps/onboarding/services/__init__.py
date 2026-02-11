"""
Onboarding email services.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, OperationalError

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
        # Check if welcome email already sent
        onboarding_status, _ = OnboardingStatus.objects.get_or_create(user=user)
        if onboarding_status.welcome_email_sent:
            logger.info("Welcome email already sent to user %s", user.id)
            return True

        context = get_email_context(user)
        html_content, plain_text_content = render_email_templates("welcome", context)

        # Handle concurrent creation with IntegrityError
        existing = OnboardingEmail.objects.filter(user=user, email_type=OnboardingEmail.EmailType.WELCOME).first()
        if existing and existing.status == OnboardingEmail.EmailStatus.SENT:
            logger.info("Welcome email record already sent for user %s", user.id)
            return True
        if existing and existing.status == OnboardingEmail.EmailStatus.FAILED:
            existing.delete()

        try:
            email_record = OnboardingEmail.create_email(
                user=user,
                email_type=OnboardingEmail.EmailType.WELCOME,
                subject="Welcome to sbomify - Let's Get Started!",
            )
        except IntegrityError:
            concurrent = OnboardingEmail.objects.filter(user=user, email_type=OnboardingEmail.EmailType.WELCOME).first()
            if concurrent and concurrent.status == OnboardingEmail.EmailStatus.SENT:
                return True
            logger.warning("Welcome email being processed by another worker for user %s", user.id)
            return False

        try:
            send_mail(
                subject=email_record.subject,
                message=plain_text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_content,
                fail_silently=False,
            )
            email_record.mark_sent()
            onboarding_status.mark_welcome_email_sent()
            logger.info("Welcome email sent successfully to user %s", user.id)
            return True
        except Exception as e:
            email_record.mark_failed(f"SMTP send failure: {type(e).__name__}")
            logger.error("Failed to send welcome email to user %s: %s", user.id, e, exc_info=True)
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
        onboarding_status = OnboardingStatus.objects.filter(user=user).first()
        if not onboarding_status:
            logger.info("No onboarding status found for user %s", user.id)
            return False

        needs_component = onboarding_status.should_receive_component_reminder()
        needs_sbom = onboarding_status.should_receive_sbom_reminder()

        if not needs_component and not needs_sbom:
            logger.info("First component/SBOM reminder not needed for user %s", user.id)
            return False

        # Dedup — only skip if successfully sent (allow retry of FAILED records)
        existing = OnboardingEmail.objects.filter(
            user=user, email_type=OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM
        ).first()
        if existing and existing.status == OnboardingEmail.EmailStatus.SENT:
            logger.info("First component/SBOM reminder already sent to user %s", user.id)
            return True

        context = get_email_context(
            user,
            has_created_component=onboarding_status.has_created_component,
            needs_component=needs_component,
            needs_sbom=needs_sbom,
        )
        html_content, plain_text_content = render_email_templates("first_component_sbom", context)

        # Delete FAILED record after render succeeds (so error history is preserved if render fails)
        if existing and existing.status == OnboardingEmail.EmailStatus.FAILED:
            existing.delete()

        if needs_component:
            subject = "Ready to Create Your First Component? - sbomify"
        else:
            subject = "Time to Upload Your First SBOM! - sbomify"

        try:
            email_record = OnboardingEmail.create_email(
                user=user, email_type=OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM, subject=subject
            )
        except IntegrityError:
            concurrent = OnboardingEmail.objects.filter(
                user=user, email_type=OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM
            ).first()
            if concurrent and concurrent.status == OnboardingEmail.EmailStatus.SENT:
                return True
            logger.warning("First component/SBOM email being processed by another worker for user %s", user.id)
            return False

        try:
            send_mail(
                subject=email_record.subject,
                message=plain_text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_content,
                fail_silently=False,
            )
            email_record.mark_sent()
            logger.info("First component/SBOM reminder sent successfully to user %s", user.id)
            return True
        except Exception as e:
            email_record.mark_failed(f"SMTP send failure: {type(e).__name__}")
            logger.error("Failed to send first component/SBOM reminder to user %s: %s", user.id, e, exc_info=True)
            return False

    @staticmethod
    def _send_onboarding_email(user, email_type: str, template_name: str, subject: str, eligible_check=None) -> bool:
        """
        Generic helper to send an onboarding sequence email.

        Checks deduplication, eligibility, and handles record creation/failure tracking.
        """
        # Dedup check — only skip if successfully sent
        existing = OnboardingEmail.objects.filter(user=user, email_type=email_type).first()
        if existing and existing.status == OnboardingEmail.EmailStatus.SENT:
            logger.info("%s email already sent to user %s", email_type, user.id)
            return True

        # Check eligibility if a check function is provided
        if eligible_check is not None:
            try:
                is_eligible = eligible_check()
            except OperationalError:
                raise
            except Exception as e:
                logger.error("%s eligibility check failed for user %s: %s", email_type, user.id, e, exc_info=True)
                return False
            if not is_eligible:
                logger.info("%s email not eligible for user %s", email_type, user.id)
                return False

        context = get_email_context(user)
        html_content, plain_text_content = render_email_templates(template_name, context)

        # Delete any previous failed record so we can create a fresh one
        if existing and existing.status == OnboardingEmail.EmailStatus.FAILED:
            existing.delete()

        try:
            email_record = OnboardingEmail.create_email(user=user, email_type=email_type, subject=subject)
        except IntegrityError:
            # Concurrent worker — verify actual status before returning
            concurrent = OnboardingEmail.objects.filter(user=user, email_type=email_type).first()
            if concurrent and concurrent.status == OnboardingEmail.EmailStatus.SENT:
                return True
            logger.warning("%s email being processed by another worker for user %s", email_type, user.id)
            return False

        try:
            send_mail(
                subject=email_record.subject,
                message=plain_text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_content,
                fail_silently=False,
            )
            email_record.mark_sent()
            logger.info("%s email sent successfully to user %s", email_type, user.id)
            return True
        except Exception as e:
            email_record.mark_failed(f"SMTP send failure: {type(e).__name__}")
            logger.error("Failed to send %s email to user %s: %s", email_type, user.id, e, exc_info=True)
            return False

    @staticmethod
    def send_quick_start_email(user) -> bool:
        """Send quick start guide email (day 1)."""
        status = OnboardingStatus.objects.filter(user=user).first()
        return OnboardingEmailService._send_onboarding_email(
            user,
            email_type=OnboardingEmail.EmailType.QUICK_START,
            template_name="quick_start",
            subject="Your quick start guide - sbomify",
            eligible_check=lambda: status is not None and status.should_receive_quick_start(),
        )

    @staticmethod
    def send_first_component_email(user) -> bool:
        """Send first component reminder email (day 3, no component created)."""
        status = OnboardingStatus.objects.filter(user=user).first()
        return OnboardingEmailService._send_onboarding_email(
            user,
            email_type=OnboardingEmail.EmailType.FIRST_COMPONENT,
            template_name="first_component",
            subject="Ready to create your first component? - sbomify",
            eligible_check=lambda: status is not None and status.should_receive_component_reminder(days_threshold=3),
        )

    @staticmethod
    def send_first_sbom_email(user) -> bool:
        """Send first SBOM upload reminder email (day 7, component exists but no SBOM)."""
        status = OnboardingStatus.objects.filter(user=user).first()
        return OnboardingEmailService._send_onboarding_email(
            user,
            email_type=OnboardingEmail.EmailType.FIRST_SBOM,
            template_name="first_sbom",
            subject="Time to upload your first SBOM - sbomify",
            eligible_check=lambda: status is not None and status.should_receive_sbom_reminder(days_threshold=7),
        )

    @staticmethod
    def send_collaboration_email(user) -> bool:
        """Send collaboration/invite email (day 10, solo workspace)."""
        status = OnboardingStatus.objects.filter(user=user).first()
        return OnboardingEmailService._send_onboarding_email(
            user,
            email_type=OnboardingEmail.EmailType.COLLABORATION,
            template_name="collaboration",
            subject="Invite your team to sbomify",
            eligible_check=lambda: status is not None and status.should_receive_collaboration(),
        )

    @staticmethod
    def get_users_for_onboarding_sequence():
        """
        Get users eligible for each onboarding sequence email.

        Returns:
            Dict mapping email_type to list of eligible User objects
        """
        from django.contrib.auth import get_user_model

        from sbomify.apps.teams.models import Member

        User = get_user_model()
        results = {
            OnboardingEmail.EmailType.QUICK_START: [],
            OnboardingEmail.EmailType.FIRST_COMPONENT: [],
            OnboardingEmail.EmailType.FIRST_SBOM: [],
            OnboardingEmail.EmailType.COLLABORATION: [],
        }

        # Get all primary workspace owners with their onboarding status
        primary_owners = Member.objects.filter(
            role="owner",
            is_default_team=True,
        ).select_related("user", "team")

        # Get all successfully sent emails to avoid re-sending
        sent_emails = set(
            OnboardingEmail.objects.filter(
                email_type__in=[
                    OnboardingEmail.EmailType.QUICK_START,
                    OnboardingEmail.EmailType.FIRST_COMPONENT,
                    OnboardingEmail.EmailType.FIRST_SBOM,
                    OnboardingEmail.EmailType.COLLABORATION,
                ],
                status=OnboardingEmail.EmailStatus.SENT,
            ).values_list("user_id", "email_type")
        )

        skipped_no_status = 0
        skipped_errors = 0
        for member in primary_owners:
            try:
                try:
                    status = OnboardingStatus.objects.get(user=member.user)
                except OnboardingStatus.DoesNotExist:
                    skipped_no_status += 1
                    continue

                user_id = member.user.id

                # Quick Start (day 1)
                if (
                    user_id,
                    OnboardingEmail.EmailType.QUICK_START,
                ) not in sent_emails and status.should_receive_quick_start(days_threshold=1):
                    results[OnboardingEmail.EmailType.QUICK_START].append(user_id)

                # First Component (day 3, no component)
                if (
                    user_id,
                    OnboardingEmail.EmailType.FIRST_COMPONENT,
                ) not in sent_emails and status.should_receive_component_reminder(days_threshold=3):
                    results[OnboardingEmail.EmailType.FIRST_COMPONENT].append(user_id)

                # First SBOM (day 7, component but no SBOM)
                if (
                    user_id,
                    OnboardingEmail.EmailType.FIRST_SBOM,
                ) not in sent_emails and status.should_receive_sbom_reminder(days_threshold=7):
                    results[OnboardingEmail.EmailType.FIRST_SBOM].append(user_id)

                # Collaboration (day 10, solo workspace)
                if (
                    user_id,
                    OnboardingEmail.EmailType.COLLABORATION,
                ) not in sent_emails and status.should_receive_collaboration(days_threshold=10):
                    results[OnboardingEmail.EmailType.COLLABORATION].append(user_id)
            except Exception as e:
                skipped_errors += 1
                logger.error("Error processing onboarding sequence for user %s: %s", member.user.id, e, exc_info=True)

        if skipped_no_status:
            logger.warning(
                "Skipped %d primary owners with missing OnboardingStatus during sequence processing",
                skipped_no_status,
            )
        if skipped_errors:
            logger.error(
                "Failed to process %d primary owners during sequence processing",
                skipped_errors,
            )

        # Convert IDs to User querysets
        return {email_type: User.objects.filter(id__in=user_ids) for email_type, user_ids in results.items()}

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

        skipped_no_status = 0
        skipped_errors = 0
        for member in primary_owners:
            try:
                try:
                    status = OnboardingStatus.objects.get(user=member.user)
                except OnboardingStatus.DoesNotExist:
                    skipped_no_status += 1
                    continue

                # Check if they need component reminder
                if status.welcome_email_sent and status.should_receive_component_reminder(days_threshold=3):
                    eligible_users.append(member.user.id)
                    continue

                # Check if they need SBOM reminder
                if status.has_created_component and status.should_receive_sbom_reminder(days_threshold=7):
                    eligible_users.append(member.user.id)
                    continue
            except Exception as e:
                skipped_errors += 1
                logger.error("Error processing legacy reminder for user %s: %s", member.user.id, e, exc_info=True)

        if skipped_no_status:
            logger.warning(
                "Skipped %d primary owners with missing OnboardingStatus during legacy reminder processing",
                skipped_no_status,
            )
        if skipped_errors:
            logger.error(
                "Failed to process %d primary owners during legacy reminder processing",
                skipped_errors,
            )

        # Filter out users who already received this email or the newer sequence equivalents
        users_already_sent = set(
            OnboardingEmail.objects.filter(
                email_type__in=[
                    OnboardingEmail.EmailType.FIRST_COMPONENT_SBOM,
                    OnboardingEmail.EmailType.FIRST_COMPONENT,
                    OnboardingEmail.EmailType.FIRST_SBOM,
                ],
                status=OnboardingEmail.EmailStatus.SENT,
            ).values_list("user_id", flat=True)
        )

        eligible_users = [uid for uid in eligible_users if uid not in users_already_sent]

        return User.objects.filter(id__in=eligible_users)
