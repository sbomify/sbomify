"""
Management command to sync billing plan prices from Stripe.

This command fetches current prices from Stripe for all billing plans
and updates the local monthly_price and annual_price fields.
"""

import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_client import StripeClient, StripeError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync billing plan prices from Stripe"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--plan-key",
            type=str,
            help="Sync only the specified plan key (e.g., 'business')",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        plan_key = options.get("plan_key")

        # Filter plans
        if plan_key:
            plans = BillingPlan.objects.filter(key=plan_key)
            if not plans.exists():
                raise CommandError(f"Plan with key '{plan_key}' not found")
        else:
            plans = BillingPlan.objects.filter(stripe_price_monthly_id__isnull=False) | BillingPlan.objects.filter(
                stripe_price_annual_id__isnull=False
            )
            plans = plans.distinct()

        if not plans.exists():
            self.stdout.write(self.style.WARNING("No plans with Stripe price IDs found"))
            return

        stripe_client = StripeClient()
        updated_count = 0
        error_count = 0

        for plan in plans:
            self.stdout.write(f"\nProcessing plan: {plan.name} ({plan.key})")

            updated = False
            errors = []

            # Sync monthly price
            if plan.stripe_price_monthly_id:
                try:
                    stripe_price = stripe_client.get_price(plan.stripe_price_monthly_id)
                    if stripe_price.unit_amount:
                        new_price = stripe_price.unit_amount / 100
                        if plan.monthly_price != new_price:
                            if dry_run:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"  Would update monthly_price: ${plan.monthly_price} → ${new_price}"
                                    )
                                )
                            else:
                                plan.monthly_price = new_price
                                updated = True
                                self.stdout.write(
                                    self.style.SUCCESS(f"  Updated monthly_price: ${plan.monthly_price} → ${new_price}")
                                )
                        else:
                            self.stdout.write(f"  Monthly price already up to date: ${plan.monthly_price}")
                except StripeError as e:
                    error_msg = f"Failed to fetch monthly price: {str(e)}"
                    errors.append(error_msg)
                    self.stdout.write(self.style.ERROR(f"  {error_msg}"))
                    logger.error("Error syncing monthly price for plan %s: %s", plan.key, str(e))

            # Sync annual price
            if plan.stripe_price_annual_id:
                try:
                    stripe_price = stripe_client.get_price(plan.stripe_price_annual_id)
                    if stripe_price.unit_amount:
                        new_price = stripe_price.unit_amount / 100
                        if plan.annual_price != new_price:
                            if dry_run:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"  Would update annual_price: ${plan.annual_price} → ${new_price}"
                                    )
                                )
                            else:
                                plan.annual_price = new_price
                                updated = True
                                self.stdout.write(
                                    self.style.SUCCESS(f"  Updated annual_price: ${plan.annual_price} → ${new_price}")
                                )
                        else:
                            self.stdout.write(f"  Annual price already up to date: ${plan.annual_price}")
                except StripeError as e:
                    error_msg = f"Failed to fetch annual price: {str(e)}"
                    errors.append(error_msg)
                    self.stdout.write(self.style.ERROR(f"  {error_msg}"))
                    logger.error("Error syncing annual price for plan %s: %s", plan.key, str(e))

            # Update last_synced_at and save if we made changes
            if updated and not dry_run:
                plan.last_synced_at = timezone.now()
                plan.save()
                updated_count += 1
            elif errors:
                error_count += 1

        # Summary
        self.stdout.write("\n" + "=" * 50)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes were made"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Successfully updated {updated_count} plan(s)"))
            if error_count > 0:
                self.stdout.write(self.style.WARNING(f"Encountered errors for {error_count} plan(s)"))
