"""
Management command to sync subscription status from Stripe.

This command identifies teams whose local subscription status may be out of sync
with Stripe (e.g., due to missed webhooks) and updates them to match Stripe's
actual state.

Usage:
    # Dry run - see what would be changed
    python manage.py sync_stripe_subscriptions --dry-run

    # Sync all teams with subscriptions
    python manage.py sync_stripe_subscriptions

    # Sync a specific team
    python manage.py sync_stripe_subscriptions --team-key ABC123

    # Only sync teams that appear to have stale trials
    python manage.py sync_stripe_subscriptions --stale-trials-only
"""

import logging
from datetime import datetime
from datetime import timezone as python_tz

from django.core.management.base import BaseCommand
from django.utils import timezone

from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.billing.stripe_client import StripeClient, StripeError
from sbomify.apps.teams.models import Team

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Sync subscription status from Stripe to local database."""

    help = "Sync subscription status from Stripe API to fix teams with stale billing data"

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--team-key",
            type=str,
            help="Sync a specific team by key",
        )
        parser.add_argument(
            "--stale-trials-only",
            action="store_true",
            help="Only sync teams with trials that appear to have expired",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed output for each team",
        )

    def handle(self, *args, **options):
        """Execute the command."""
        dry_run = options["dry_run"]
        team_key = options["team_key"]
        stale_trials_only = options["stale_trials_only"]
        verbose = options["verbose"]

        if not is_billing_enabled():
            self.stdout.write(self.style.WARNING("Billing is not enabled. Exiting."))
            return

        stripe_client = StripeClient()

        # Build queryset
        if team_key:
            teams = Team.objects.filter(key=team_key)
            if not teams.exists():
                self.stdout.write(self.style.ERROR(f"Team with key '{team_key}' not found"))
                return
        else:
            # Get all teams with Stripe subscription IDs
            teams = Team.objects.exclude(billing_plan_limits__isnull=True).filter(
                billing_plan_limits__has_key="stripe_subscription_id"
            )

        if stale_trials_only:
            # Filter to teams that appear to be trialing but trial_end is in the past
            now_timestamp = int(timezone.now().timestamp())
            filtered_teams = []
            for team in teams:
                limits = team.billing_plan_limits or {}
                if limits.get("is_trial") or limits.get("subscription_status") == "trialing":
                    trial_end = limits.get("trial_end")
                    if trial_end and trial_end < now_timestamp:
                        filtered_teams.append(team)
            teams = filtered_teams
            self.stdout.write(f"Found {len(teams)} teams with potentially stale trials")
        else:
            teams = list(teams)
            self.stdout.write(f"Found {len(teams)} teams with Stripe subscriptions")

        if not teams:
            self.stdout.write(self.style.SUCCESS("No teams to sync."))
            return

        # Track statistics
        synced = 0
        already_in_sync = 0
        errors = 0
        changes = []

        for team in teams:
            result = self._sync_team(team, stripe_client, dry_run, verbose)
            if result == "synced":
                synced += 1
                changes.append(team.key)
            elif result == "in_sync":
                already_in_sync += 1
            else:
                errors += 1

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("SUMMARY:")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes were made"))
        self.stdout.write(f"  Teams synced: {synced}")
        self.stdout.write(f"  Already in sync: {already_in_sync}")
        self.stdout.write(f"  Errors: {errors}")

        if changes:
            self.stdout.write(f"\nTeams updated: {', '.join(changes)}")

    def _sync_team(self, team: Team, stripe_client: StripeClient, dry_run: bool, verbose: bool) -> str:
        """
        Sync a single team's subscription status from Stripe.

        Returns:
            "synced" if changes were made
            "in_sync" if no changes needed
            "error" if an error occurred
        """
        limits = team.billing_plan_limits or {}
        subscription_id = limits.get("stripe_subscription_id")

        if not subscription_id:
            if verbose:
                self.stdout.write(f"  {team.key}: No subscription ID, skipping")
            return "in_sync"

        try:
            # Fetch actual subscription from Stripe
            subscription = stripe_client.get_subscription(subscription_id)

            # Get current local state
            local_status = limits.get("subscription_status")
            local_is_trial = limits.get("is_trial", False)

            # Get Stripe's actual state
            stripe_status = subscription.status
            stripe_is_trial = stripe_status == "trialing"

            # Check if trial has expired
            trial_end = subscription.trial_end
            trial_expired = False
            if trial_end:
                trial_end_dt = datetime.fromtimestamp(trial_end, tz=python_tz.utc)
                if trial_end_dt < timezone.now():
                    trial_expired = True

            # Determine if update is needed
            needs_update = False
            update_reasons = []

            if local_status != stripe_status:
                needs_update = True
                update_reasons.append(f"status: {local_status} -> {stripe_status}")

            if local_is_trial != stripe_is_trial:
                needs_update = True
                update_reasons.append(f"is_trial: {local_is_trial} -> {stripe_is_trial}")

            if not needs_update:
                if verbose:
                    self.stdout.write(f"  {team.key}: Already in sync (status={stripe_status})")
                return "in_sync"

            # Log the changes
            reasons_str = ", ".join(update_reasons)
            self.stdout.write(f"  {team.key}: {reasons_str}")

            if dry_run:
                self.stdout.write(self.style.WARNING(f"    Would update {team.name}"))
                return "synced"

            # Apply updates
            team.billing_plan_limits["subscription_status"] = stripe_status
            team.billing_plan_limits["is_trial"] = stripe_is_trial
            team.billing_plan_limits["last_updated"] = timezone.now().isoformat()
            team.billing_plan_limits["last_synced_from_stripe"] = timezone.now().isoformat()

            # If trial expired, clear trial fields
            if trial_expired and not stripe_is_trial:
                team.billing_plan_limits["trial_days_remaining"] = 0

            team.save()

            self.stdout.write(self.style.SUCCESS(f"    Updated {team.name}"))
            logger.info(f"Synced subscription status for team {team.key}: {reasons_str}")
            return "synced"

        except StripeError as e:
            self.stdout.write(self.style.ERROR(f"  {team.key}: Stripe error - {e}"))
            logger.error(f"Failed to sync team {team.key}: {e}")
            return "error"
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  {team.key}: Unexpected error - {e}"))
            logger.exception(f"Failed to sync team {team.key}: {e}")
            return "error"
