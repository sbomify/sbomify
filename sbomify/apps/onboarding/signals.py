"""
Signal handlers for tracking onboarding progress.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.core.models import Component, User
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team
from sbomify.logging import getLogger

from .models import OnboardingStatus

logger = getLogger(__name__)


@receiver(post_save, sender=User)
def create_onboarding_status(sender: type[Any], instance: User, created: bool, **kwargs: Any) -> None:
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
            logger.info("Created onboarding status for user %s", instance.id)
        except Exception as e:
            logger.error("Failed to create onboarding status for user %s: %s", instance.id, e, exc_info=True)
            return

        try:
            from .tasks import queue_welcome_email

            task_id = queue_welcome_email(instance)
            logger.info("Queued welcome email task %s for user %s", task_id, instance.id)
        except Exception as e:
            logger.error("Failed to queue welcome email for user %s: %s", instance.id, e, exc_info=True)


@receiver(post_save, sender=Component)
def track_first_component_creation(sender: type[Any], instance: Component, created: bool, **kwargs: Any) -> None:
    """
    Track when a workspace gets its first BOM component.

    Only tracks BOM components for PRIMARY workspace owners to avoid duplicate notifications.

    Args:
        sender: The Component model class
        instance: The Component instance that was saved
        created: Whether this is a new component
        **kwargs: Additional keyword arguments
    """
    if created and instance.team and instance.component_type == Component.ComponentType.BOM:
        try:
            from sbomify.apps.teams.models import Member

            # Check if this is the first BOM component in the workspace
            bom_component_count = Component.objects.filter(
                team=instance.team, component_type=Component.ComponentType.BOM
            ).count()

            if bom_component_count == 1:  # This is the first BOM component in the workspace
                # Get PRIMARY owners only (avoid multiple notifications)
                primary_owners = Member.objects.filter(
                    team=instance.team,
                    role="owner",
                    is_default_team=True,  # Only their primary workspace
                ).select_related("user")

                for member in primary_owners:
                    onboarding_status, _ = OnboardingStatus.objects.get_or_create(user=member.user)
                    onboarding_status.mark_component_created()
                    logger.info("Marked first BOM component creation for workspace owner %s", member.user.id)

                from django.db import transaction

                from sbomify.apps.core.posthog_service import capture

                component_id = instance.id
                workspace_key = instance.team.key
                distinct_id = workspace_key or "system"
                groups = {"workspace": workspace_key} if workspace_key else None
                transaction.on_commit(
                    lambda: capture(
                        distinct_id,
                        "component:first_created",
                        {"component_id": component_id},
                        groups=groups,
                    )
                )

        except Exception as e:
            logger.error("Failed to track BOM component creation: %s", e, exc_info=True)


@receiver(post_save, sender=SBOM)
def track_first_bom_artifact_upload(sender: type[Any], instance: SBOM, created: bool, **kwargs: Any) -> None:
    """
    Track when a workspace gets its first BOM artifact (SBOM, VEX, CBOM, etc.).

    Only tracks for PRIMARY workspace owners to avoid duplicate notifications.

    Args:
        sender: The SBOM model class
        instance: The SBOM instance that was saved
        created: Whether this is a new BOM artifact
        **kwargs: Additional keyword arguments
    """
    if created and instance.component and instance.component.team:
        try:
            from sbomify.apps.teams.models import Member

            # Check if this is the first BOM artifact in the workspace
            bom_count = SBOM.objects.filter(component__team=instance.component.team).count()

            if bom_count == 1:  # This is the first BOM artifact in the workspace
                # Get PRIMARY owners only (avoid multiple notifications)
                primary_owners = Member.objects.filter(
                    team=instance.component.team,
                    role="owner",
                    is_default_team=True,  # Only their primary workspace
                ).select_related("user")

                for member in primary_owners:
                    onboarding_status, _ = OnboardingStatus.objects.get_or_create(user=member.user)
                    onboarding_status.mark_sbom_uploaded()
                    logger.info("Marked first BOM artifact upload for workspace owner %s", member.user.id)

                from django.db import transaction

                from sbomify.apps.core.posthog_service import capture

                team = instance.component.team
                component_id = instance.component.id
                workspace_key = team.key
                distinct_id = workspace_key or "system"
                groups = {"workspace": workspace_key} if workspace_key else None
                transaction.on_commit(
                    lambda: capture(
                        distinct_id,
                        "bom_artifact:first_uploaded",
                        {"component_id": component_id},
                        groups=groups,
                    )
                )

        except Exception as e:
            logger.error("Failed to track BOM artifact upload: %s", e, exc_info=True)


@receiver(post_save, sender=Team)
def track_wizard_completion(sender: type[Any], instance: Team, created: bool, **kwargs: Any) -> None:
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

            any_transitioned = False
            for member in team_owners:
                onboarding_status, _ = OnboardingStatus.objects.get_or_create(user=member.user)
                if not onboarding_status.has_completed_wizard:
                    onboarding_status.mark_wizard_completed()
                    any_transitioned = True
                    logger.info("Marked wizard completion for user %s", member.user.id)

            if any_transitioned:
                from django.db import transaction

                from sbomify.apps.core.posthog_service import capture

                workspace_key = instance.key
                distinct_id = workspace_key or "system"
                groups = {"workspace": workspace_key} if workspace_key else None
                transaction.on_commit(lambda: capture(distinct_id, "onboarding:wizard_completed", groups=groups))

        except Exception as e:
            logger.error("Failed to track wizard completion: %s", e, exc_info=True)
