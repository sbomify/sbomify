from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

from sbomify.apps.core.utils import generate_id

if TYPE_CHECKING:
    from sbomify.apps.core.models import User


class OnboardingStatus(models.Model):
    """Track user onboarding progress and milestones."""

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    user = models.OneToOneField("core.User", on_delete=models.CASCADE, related_name="onboarding_status")

    # Progress tracking
    has_created_component = models.BooleanField(
        default=False, help_text="Whether the user has created their first component"
    )
    first_component_created_at = models.DateTimeField(
        null=True, blank=True, help_text="When the user created their first component"
    )

    has_uploaded_sbom = models.BooleanField(default=False, help_text="Whether the user has uploaded their first SBOM")
    first_sbom_uploaded_at = models.DateTimeField(
        null=True, blank=True, help_text="When the user uploaded their first SBOM"
    )

    has_completed_wizard = models.BooleanField(
        default=False, help_text="Whether the user has completed the onboarding wizard"
    )
    wizard_completed_at = models.DateTimeField(
        null=True, blank=True, help_text="When the user completed the onboarding wizard"
    )

    # Email tracking
    welcome_email_sent = models.BooleanField(default=False, help_text="Whether the welcome email has been sent")
    welcome_email_sent_at = models.DateTimeField(null=True, blank=True, help_text="When the welcome email was sent")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "onboarding_onboardingstatus"
        verbose_name = "Onboarding Status"
        verbose_name_plural = "Onboarding Statuses"
        indexes = [
            models.Index(fields=["has_completed_wizard"]),
            models.Index(fields=["has_created_component"]),
            models.Index(fields=["has_uploaded_sbom"]),
        ]

    def __str__(self) -> str:
        return f"OnboardingStatus for {self.user.email}"

    def mark_component_created(self) -> None:
        """Mark that the user has created their first component."""
        if not self.has_created_component:
            self.has_created_component = True
            self.first_component_created_at = timezone.now()
            self.save(update_fields=["has_created_component", "first_component_created_at"])

    def mark_sbom_uploaded(self) -> None:
        """Mark that the user has uploaded their first SBOM."""
        if not self.has_uploaded_sbom:
            self.has_uploaded_sbom = True
            self.first_sbom_uploaded_at = timezone.now()
            self.save(update_fields=["has_uploaded_sbom", "first_sbom_uploaded_at"])

    def mark_wizard_completed(self) -> None:
        """Mark that the user has completed the onboarding wizard."""
        if not self.has_completed_wizard:
            self.has_completed_wizard = True
            self.wizard_completed_at = timezone.now()
            self.save(update_fields=["has_completed_wizard", "wizard_completed_at"])

    def mark_welcome_email_sent(self) -> None:
        """Mark that the welcome email has been sent."""
        if not self.welcome_email_sent:
            self.welcome_email_sent = True
            self.welcome_email_sent_at = timezone.now()
            self.save(update_fields=["welcome_email_sent", "welcome_email_sent_at"])

    @property
    def user_role(self) -> str:
        """Get the user's role in their primary workspace."""
        from sbomify.apps.teams.models import Member

        try:
            member = Member.objects.get(user=self.user, is_default_team=True)
            return member.role
        except Member.DoesNotExist:
            return "member"

    @property
    def days_since_signup(self) -> int:
        """Calculate days since user signup."""
        return (timezone.now() - self.created_at).days

    def should_receive_component_reminder(self, days_threshold: int = 3) -> bool:
        """
        Check if user should receive SBOM component creation reminder.

        Only for workspace owners who:
        - Have had welcome email sent
        - Signed up X+ days ago
        - Haven't created any SBOM components in their workspace
        """
        if not self.welcome_email_sent:
            return False

        if self.days_since_signup < days_threshold:
            return False

        # Check if user is a workspace owner
        if self.user_role != "owner":
            return False

        # Check if their workspace has any SBOM components
        from sbomify.apps.core.models import Component
        from sbomify.apps.teams.models import Member

        try:
            member = Member.objects.get(user=self.user, is_default_team=True)
            sbom_component_count = Component.objects.filter(
                team=member.team, component_type=Component.ComponentType.SBOM
            ).count()
            return sbom_component_count == 0
        except Member.DoesNotExist:
            return False

    def should_receive_quick_start(self, days_threshold: int = 1) -> bool:
        """
        Check if user should receive quick start guide email.

        Only for workspace owners who:
        - Have had welcome email sent
        - Signed up at least 1 day ago
        """
        if not self.welcome_email_sent:
            return False

        if self.user_role != "owner":
            return False

        return self.days_since_signup >= days_threshold

    def should_receive_collaboration(self, days_threshold: int = 10) -> bool:
        """
        Check if user should receive collaboration/invite email.

        Only for workspace owners who:
        - Have had welcome email sent
        - Signed up 10+ days ago
        - Are still the only member in their workspace (no invites sent)
        """
        if not self.welcome_email_sent:
            return False

        if self.days_since_signup < days_threshold:
            return False

        if self.user_role != "owner":
            return False

        from sbomify.apps.teams.models import Member

        try:
            member = Member.objects.get(user=self.user, is_default_team=True)
            team_member_count = Member.objects.filter(team=member.team).count()
            return team_member_count <= 1
        except Member.DoesNotExist:
            return False

    def should_receive_sbom_reminder(self, days_threshold: int = 7) -> bool:
        """
        Check if user should receive SBOM upload reminder.

        Only for workspace owners who:
        - Have created components
        - Created components X+ days ago
        - Haven't uploaded any SBOMs to their workspace
        """
        if not self.has_created_component:
            return False

        if not self.first_component_created_at:
            return False

        days_since_component = (timezone.now() - self.first_component_created_at).days
        if days_since_component < days_threshold:
            return False

        # Check if user is a workspace owner
        if self.user_role != "owner":
            return False

        # Check if their workspace has any SBOMs
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.teams.models import Member

        try:
            member = Member.objects.get(user=self.user, is_default_team=True)
            sbom_count = SBOM.objects.filter(component__team=member.team).count()
            return sbom_count == 0
        except Member.DoesNotExist:
            return False


class OnboardingEmail(models.Model):
    """Track onboarding emails sent to users."""

    class EmailType(models.TextChoices):
        WELCOME = "welcome", "Welcome"
        QUICK_START = "quick_start", "Quick Start Guide"
        FIRST_COMPONENT = "first_component", "First Component"
        FIRST_SBOM = "first_sbom", "First SBOM"
        COLLABORATION = "collaboration", "Team Collaboration"
        FIRST_COMPONENT_SBOM = "first_component_sbom", "First Component/SBOM"

    class EmailStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    id = models.CharField(max_length=20, primary_key=True, default=generate_id)
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="onboarding_emails")
    email_type = models.CharField(max_length=50, choices=EmailType.choices)
    status = models.CharField(max_length=20, choices=EmailStatus.choices, default=EmailStatus.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Email metadata
    subject = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "onboarding_onboardingemail"
        unique_together = ("user", "email_type")
        verbose_name = "Onboarding Email"
        verbose_name_plural = "Onboarding Emails"

    def __str__(self) -> str:
        return f"{self.get_email_type_display()} email for {self.user.email}"

    @classmethod
    def create_email(cls, user: User, email_type: str, subject: str = "") -> "OnboardingEmail":
        """Create a new onboarding email record."""
        return cls.objects.create(user=user, email_type=email_type, subject=subject)

    def mark_sent(self) -> None:
        """Mark email as successfully sent."""
        self.status = self.EmailStatus.SENT
        self.sent_at = timezone.now()
        self.save(update_fields=["status", "sent_at"])

    def mark_failed(self, error_message: str = "") -> None:
        """Mark email as failed with optional error message."""
        self.status = self.EmailStatus.FAILED
        self.error_message = error_message
        self.retry_count += 1
        self.save(update_fields=["status", "error_message", "retry_count"])
