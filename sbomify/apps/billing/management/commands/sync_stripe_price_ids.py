"""
Management command to sync Stripe price IDs for billing plans.

This command fetches existing Stripe products and prices and updates the
BillingPlan records with the correct price IDs.

Useful for fixing situations where test price IDs are stored in the database
but the application is using a real Stripe API key.
"""

import logging

import stripe
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.utils import is_test_environment

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync Stripe price IDs for billing plans from Stripe API"

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
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update even if price IDs already exist",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        plan_key = options.get("plan_key")
        force = options.get("force", False)

        if is_test_environment():
            self.stdout.write(
                self.style.WARNING("Detected test environment. This command should be run with a real Stripe API key.")
            )
            if not force:
                raise CommandError("Cannot sync Stripe price IDs in test environment. Use --force to override.")

        if not settings.STRIPE_SECRET_KEY:
            raise CommandError("STRIPE_SECRET_KEY is not set in settings")

        if plan_key:
            plans = BillingPlan.objects.filter(key=plan_key)
            if not plans.exists():
                raise CommandError(f"Plan with key '{plan_key}' not found")
        else:
            # Sync any plan that has a price associated with it
            plans = BillingPlan.objects.filter(Q(monthly_price__gt=0) | Q(annual_price__gt=0))

        if not plans.exists():
            self.stdout.write(self.style.WARNING("No plans found to sync"))
            return

        stripe.api_key = settings.STRIPE_SECRET_KEY

        updated_count = 0
        error_count = 0

        try:
            existing_products = {p.name.lower(): p for p in stripe.Product.list(active=True, limit=100).data}

            for plan in plans:
                self.stdout.write(f"\nProcessing plan: {plan.name} ({plan.key})")

                try:
                    product = self._get_or_create_product(plan, existing_products, dry_run)
                    if not product:
                        continue

                    plan_updated = self._sync_prices(plan, product, force, dry_run)

                    if plan_updated and not dry_run:
                        plan._skip_team_update = True
                        plan.save(
                            update_fields=[
                                "stripe_product_id",
                                "stripe_price_monthly_id",
                                "stripe_price_annual_id",
                            ]
                        )
                        updated_count += 1
                        self.stdout.write(self.style.SUCCESS(f"  ✓ Updated plan {plan.name}"))

                except stripe.error.StripeError as e:
                    error_count += 1
                    self.stdout.write(self.style.ERROR(f"  Stripe error: {str(e)}"))
                    logger.error(f"Stripe error for plan {plan.key}: {str(e)}", exc_info=True)
                except Exception as e:
                    error_count += 1
                    self.stdout.write(self.style.ERROR(f"  Unexpected error: {str(e)}"))
                    logger.error(f"Unexpected error for plan {plan.key}: {str(e)}", exc_info=True)

        except Exception as e:
            raise CommandError(f"Failed to sync Stripe price IDs: {str(e)}")

        self.stdout.write("\n" + "=" * 50)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes were made"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Successfully updated {updated_count} plan(s)"))
            if error_count > 0:
                self.stdout.write(self.style.WARNING(f"Encountered errors for {error_count} plan(s)"))

    def _get_or_create_product(self, plan, existing_products, dry_run):
        """Get existing product or create new one."""
        product_name = plan.name

        # Check if product exists by name
        if product_name.lower() in existing_products:
            product = existing_products[product_name.lower()]
            self.stdout.write(self.style.SUCCESS(f"  Using existing product {product_name} ({product.id})"))
            return product

        # Check if we have a product ID stored and it's valid
        if plan.stripe_product_id and plan.stripe_product_id.startswith("prod_"):
            try:
                product = stripe.Product.retrieve(plan.stripe_product_id)
                self.stdout.write(self.style.SUCCESS(f"  Using stored product ID ({product.id})"))
                return product
            except stripe.error.InvalidRequestError:
                pass

        if dry_run:
            self.stdout.write(self.style.WARNING(f"  Would create new product: {product_name}"))
            return type("MockProduct", (), {"id": f"prod_new_{plan.key}"})()

        product = stripe.Product.create(
            name=product_name,
            description=plan.description or "",
        )
        self.stdout.write(self.style.SUCCESS(f"  Created new product {product_name} ({product.id})"))
        return product

    def _sync_prices(self, plan, product, force, dry_run):
        """Sync price IDs from existing Stripe prices."""
        plan_updated = False

        if not dry_run:
            existing_prices = stripe.Price.list(product=product.id, active=True, limit=100).data
        else:
            existing_prices = []

        # Find monthly price
        monthly_price = next((p for p in existing_prices if p.recurring and p.recurring.interval == "month"), None)
        if monthly_price:
            amount = monthly_price.unit_amount / 100
            self.stdout.write(f"  Found monthly price: ${amount}/month ({monthly_price.id})")
            if force or plan.stripe_price_monthly_id != monthly_price.id:
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Would update stripe_price_monthly_id: "
                            f"{plan.stripe_price_monthly_id} → {monthly_price.id}"
                        )
                    )
                else:
                    plan.stripe_price_monthly_id = monthly_price.id
                    plan_updated = True
        else:
            self.stdout.write(self.style.WARNING("  No monthly price found in Stripe for this product"))

        # Find annual price
        annual_price = next((p for p in existing_prices if p.recurring and p.recurring.interval == "year"), None)
        if annual_price:
            amount = annual_price.unit_amount / 100
            self.stdout.write(f"  Found annual price: ${amount}/year ({annual_price.id})")
            if force or plan.stripe_price_annual_id != annual_price.id:
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Would update stripe_price_annual_id: {plan.stripe_price_annual_id} → {annual_price.id}"
                        )
                    )
                else:
                    plan.stripe_price_annual_id = annual_price.id
                    plan_updated = True
        else:
            self.stdout.write(self.style.WARNING("  No annual price found in Stripe for this product"))

        # Update product ID if needed
        if force or plan.stripe_product_id != product.id:
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(f"  Would update stripe_product_id: {plan.stripe_product_id} → {product.id}")
                )
            else:
                plan.stripe_product_id = product.id
                plan_updated = True

        return plan_updated
