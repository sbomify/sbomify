"""
Management command to fix users who have missing trial subscriptions due to empty email addresses.

This command identifies users who:
1. Have empty or missing email addresses
2. Have teams but no billing subscriptions
3. Should have trial subscriptions but don't due to the email bug

It then attempts to fix their email addresses and create the missing trial subscriptions.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_client import StripeClient
from sbomify.apps.teams.models import Team

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = "Fix users with missing trial subscriptions due to empty email addresses"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--fix-emails",
            action="store_true",
            help="Attempt to fix email addresses from social accounts",
        )
        parser.add_argument(
            "--create-subscriptions",
            action="store_true",
            help="Create missing trial subscriptions for users with valid emails",
        )
        parser.add_argument(
            "--user-id",
            type=int,
            help="Fix a specific user by ID",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        fix_emails = options["fix_emails"]
        create_subscriptions = options["create_subscriptions"]
        user_id = options["user_id"]

        if not is_billing_enabled():
            self.stdout.write(self.style.WARNING("Billing is not enabled. No subscriptions will be created."))
            return

        if not fix_emails and not create_subscriptions:
            self.stdout.write(
                self.style.WARNING(
                    "Please specify --fix-emails and/or --create-subscriptions. "
                    "Use --dry-run to see what would be done."
                )
            )
            return

        if user_id:
            users = User.objects.filter(id=user_id)
            if not users.exists():
                raise CommandError(f"User with ID {user_id} not found")
        else:
            # Find teams without billing subscriptions
            teams_without_billing = []
            for team in Team.objects.all():
                if not team.billing_plan_limits or not team.billing_plan_limits.get("stripe_subscription_id"):
                    teams_without_billing.append(team)

            # Get unique users who own these teams
            user_ids = set()
            for team in teams_without_billing:
                owners = team.members.filter(member__role="owner")
                for owner in owners:
                    user_ids.add(owner.id)

            users = User.objects.filter(id__in=user_ids)

        if not users.exists():
            self.stdout.write(self.style.SUCCESS("No users found with teams missing billing subscriptions."))
            return

        self.stdout.write(f"Found {users.count()} users with teams missing billing subscriptions")

        stripe_client = StripeClient()
        fixed_emails = 0
        created_subscriptions = 0
        errors = 0

        for user in users:
            self.stdout.write(f"\nProcessing user: {user.username} (ID: {user.id})")
            self.stdout.write(f"  Current email: {user.email or '(empty)'}")

            # Show user's teams
            user_teams = Team.objects.filter(members=user)
            for team in user_teams:
                has_billing = team.billing_plan_limits and team.billing_plan_limits.get("stripe_subscription_id")
                status = "✓ Has billing" if has_billing else "✗ Missing billing"
                self.stdout.write(f"  Team: {team.name} ({team.key}) - {status}")

            # Try to fix email address if needed
            if fix_emails and not user.email:
                if self.fix_user_email(user, dry_run):
                    fixed_emails += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Fixed email address: {user.email}"))
                elif not user.email:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ✗ Could not fix email address for {user.username} - skipping subscription creation"
                        )
                    )
                    errors += 1
                    continue

            # Check if user has email
            if not user.email:
                self.stdout.write(
                    self.style.WARNING(f"  ✗ User {user.username} has no email - cannot create subscription")
                )
                errors += 1
                continue

            # Create trial subscription
            if create_subscriptions:
                if self.create_trial_subscription(user, stripe_client, dry_run):
                    created_subscriptions += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Created trial subscription for {user.username}"))
                else:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"  ✗ Failed to create trial subscription for {user.username}"))

        # Summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("SUMMARY:")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes were made"))
        else:
            self.stdout.write(f"Fixed email addresses: {fixed_emails}")
            self.stdout.write(f"Created trial subscriptions: {created_subscriptions}")
            self.stdout.write(f"Errors: {errors}")

    def fix_user_email(self, user, dry_run=False):
        """Attempt to fix a user's email address from their social accounts."""
        from allauth.socialaccount.models import SocialAccount

        # Look for social accounts with email information
        social_accounts = SocialAccount.objects.filter(user=user)

        for social_account in social_accounts:
            extra_data = social_account.extra_data or {}
            email = extra_data.get("email")

            if email and email.strip():
                if not dry_run:
                    user.email = email.strip()
                    user.save()
                    logger.info(f"Fixed email for user {user.username}: {email}")
                return True

        # If no social account email found, try to get it from the social account data
        for social_account in social_accounts:
            if hasattr(social_account, "extra_data") and social_account.extra_data:
                # Try different possible email fields
                for email_field in ["email", "emailAddress", "mail"]:
                    email = social_account.extra_data.get(email_field)
                    if email and email.strip():
                        if not dry_run:
                            user.email = email.strip()
                            user.save()
                            logger.info(f"Fixed email for user {user.username} from {email_field}: {email}")
                        return True

        return False

    def create_trial_subscription(self, user, stripe_client, dry_run=False):
        """Create a trial subscription for a user."""
        try:
            # Get the user's default team
            team = Team.objects.filter(members=user, members__is_default_team=True).first()
            if not team:
                team = Team.objects.filter(members=user).first()

            if not team:
                self.stdout.write(self.style.WARNING(f"  No team found for user {user.username}"))
                return False

            # Check if team already has a subscription
            if team.billing_plan_limits and team.billing_plan_limits.get("stripe_subscription_id"):
                self.stdout.write(self.style.WARNING(f"  Team {team.name} already has a subscription"))
                return True

            if dry_run:
                self.stdout.write(f"  Would create trial subscription for team {team.name}")
                return True

            # Create the trial subscription
            business_plan = BillingPlan.objects.get(key="business")

            with transaction.atomic():
                customer = stripe_client.create_customer(
                    email=user.email, name=team.name, metadata={"team_key": team.key}
                )

                subscription = stripe_client.create_subscription(
                    customer_id=customer.id,
                    price_id=business_plan.stripe_price_monthly_id,
                    trial_days=settings.TRIAL_PERIOD_DAYS,
                    metadata={"team_key": team.key, "plan_key": "business"},
                )

                team.billing_plan = "business"
                team.billing_plan_limits = {
                    "max_products": business_plan.max_products,
                    "max_projects": business_plan.max_projects,
                    "max_components": business_plan.max_components,
                    "stripe_customer_id": customer.id,
                    "stripe_subscription_id": subscription.id,
                    "subscription_status": "trialing",
                    "is_trial": True,
                    "trial_end": subscription.trial_end,
                    "last_updated": timezone.now().isoformat(),
                }
                team.save()

                logger.info(f"Created trial subscription for team {team.key} ({team.name})")
                return True

        except Exception as e:
            logger.error(f"Failed to create trial subscription for user {user.username}: {str(e)}")
            return False
