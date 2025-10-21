"""
Signal handlers for tracking onboarding progress.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.core.models import Component, User
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team
from sbomify.logging import getLogger

from .models import OnboardingStatus

logger = getLogger(__name__)


@receiver(post_save, sender=User)
def create_onboarding_status(sender, instance: User, created: bool, **kwargs) -> None:
    """
    Create an OnboardingStatus record when a new user is created and queue welcome email.

    Args:
        sender: The User model class
        instance: The User instance that was saved
        created: Whether this is a new user
        **kwargs: Additional keyword arguments
    """
    if created:
        try:
            OnboardingStatus.objects.create(user=instance)
            logger.info(f"Created onboarding status for user {instance.email}")

            # Queue welcome email task (lazy import to avoid circular dependency)
            from .tasks import queue_welcome_email

            task_id = queue_welcome_email(instance)
            logger.info(f"Queued welcome email task {task_id} for user {instance.email}")

        except Exception as e:
            logger.error(f"Failed to create onboarding status or queue welcome email for user {instance.email}: {e}")


@receiver(post_save, sender=Component)
def track_first_component_creation(sender, instance: Component, created: bool, **kwargs) -> None:
    """
    Track when a workspace gets its first SBOM component.

    Only tracks SBOM components for PRIMARY workspace owners to avoid duplicate notifications.

    Args:
        sender: The Component model class
        instance: The Component instance that was saved
        created: Whether this is a new component
        **kwargs: Additional keyword arguments
    """
    if created and instance.team and instance.component_type == Component.ComponentType.SBOM:
        try:
            from sbomify.apps.teams.models import Member

            # Check if this is the first SBOM component in the workspace
            sbom_component_count = Component.objects.filter(
                team=instance.team, component_type=Component.ComponentType.SBOM
            ).count()

            if sbom_component_count == 1:  # This is the first SBOM component in the workspace
                # Get PRIMARY owners only (avoid multiple notifications)
                primary_owners = Member.objects.filter(
                    team=instance.team,
                    role="owner",
                    is_default_team=True,  # Only their primary workspace
                ).select_related("user")

                for member in primary_owners:
                    onboarding_status, _ = OnboardingStatus.objects.get_or_create(user=member.user)
                    onboarding_status.mark_component_created()
                    logger.info(f"Marked first SBOM component creation for workspace owner {member.user.email}")

        except Exception as e:
            logger.error(f"Failed to track SBOM component creation: {e}")


@receiver(post_save, sender=SBOM)
def track_first_sbom_upload(sender, instance: SBOM, created: bool, **kwargs) -> None:
    """
    Track when a workspace gets its first SBOM.

    Only tracks for PRIMARY workspace owners to avoid duplicate notifications.

    Args:
        sender: The SBOM model class
        instance: The SBOM instance that was saved
        created: Whether this is a new SBOM
        **kwargs: Additional keyword arguments
    """
    if created and instance.component and instance.component.team:
        try:
            # Check if this is the first SBOM in the workspace

            from sbomify.apps.teams.models import Member

            sbom_count = SBOM.objects.filter(component__team=instance.component.team).count()

            if sbom_count == 1:  # This is the first SBOM in the workspace
                # Get PRIMARY owners only (avoid multiple notifications)
                primary_owners = Member.objects.filter(
                    team=instance.component.team,
                    role="owner",
                    is_default_team=True,  # Only their primary workspace
                ).select_related("user")

                for member in primary_owners:
                    onboarding_status, _ = OnboardingStatus.objects.get_or_create(user=member.user)
                    onboarding_status.mark_sbom_uploaded()
                    logger.info(f"Marked first SBOM upload for workspace owner {member.user.email}")

        except Exception as e:
            logger.error(f"Failed to track SBOM upload: {e}")


@receiver(post_save, sender=Team)
def track_wizard_completion(sender, instance: Team, created: bool, **kwargs) -> None:
    """
    Track when a user completes the onboarding wizard (team setup).

    Args:
        sender: The Team model class
        instance: The Team instance that was saved
        created: Whether this is a new team
        **kwargs: Additional keyword arguments
    """
    if not created and instance.has_completed_wizard:
        try:
            # Get all team owners
            from sbomify.apps.teams.models import Member

            team_owners = Member.objects.filter(team=instance, role="owner").select_related("user")

            for member in team_owners:
                onboarding_status, _ = OnboardingStatus.objects.get_or_create(user=member.user)
                onboarding_status.mark_wizard_completed()
                logger.info(f"Marked wizard completion for user {member.user.email}")

        except Exception as e:
            logger.error(f"Failed to track wizard completion: {e}")
