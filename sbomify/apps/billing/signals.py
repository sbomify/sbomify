"""
Signals for billing app to handle automatic updates when BillingPlan changes.
"""

import logging

from django.apps import apps
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import BillingPlan

logger = logging.getLogger(__name__)


@receiver(post_save, sender=BillingPlan)
def update_teams_on_plan_change(sender, instance, created, **kwargs):
    """Update all teams when a BillingPlan is saved.

    Skips update when:
    - _skip_team_update flag is set (during pricing sync from Stripe)
    - Only pricing-related fields were updated (no limit changes)
    - This is a new plan (no teams exist yet)
    - Running during migrations (apps not fully loaded)
    """
    # Skip if explicitly flagged (e.g., during Stripe sync)
    if getattr(instance, "_skip_team_update", False):
        return

    # Skip if this is a new plan (no teams to update)
    if created:
        return

    # Skip during migrations - Team model may not be available
    try:
        if not apps.is_installed("teams"):
            return
        # Verify Team model is available
        apps.get_model("teams", "Team")
    except (LookupError, ValueError):
        # Model not available during migrations
        return

    # Skip if only updating sync-related fields (no limit changes)
    update_fields = kwargs.get("update_fields")
    if update_fields:
        limit_fields = {
            "max_products",
            "max_projects",
            "max_components",
            "max_users",
        }
        # Only update teams if limit fields changed
        if not limit_fields.intersection(set(update_fields)):
            return

    # Update teams in a transaction for atomicity
    try:
        with transaction.atomic():
            instance._update_teams_with_new_limits()
            logger.info("Successfully updated teams for plan %s", instance.key)
    except Exception as e:
        # Log but don't raise - signal failures shouldn't prevent plan saves
        logger.exception(
            "Error updating teams for plan %s: %s. Teams may need manual update.",
            instance.key,
            str(e),
        )
