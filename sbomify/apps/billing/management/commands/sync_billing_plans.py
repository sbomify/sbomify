"""
Management command to sync billing plan prices from Stripe.

This command fetches current prices from Stripe for all billing plans
and updates the local monthly_price and annual_price fields.
It also handles plans without Stripe IDs by finding or creating them.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from sbomify.apps.billing.stripe_sync import sync_plan_prices_from_stripe

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync billing plan prices from Stripe"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--plan-key",
            type=str,
            help="Sync only the specified plan key (e.g., 'business')",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        plan_key: str | None = options.get("plan_key")

        self.stdout.write("Starting price sync from Stripe...")
        if plan_key:
            self.stdout.write(f"Syncing plan: {plan_key}")
        else:
            self.stdout.write("Syncing all plans...")

        # Use the centralized sync function
        results = sync_plan_prices_from_stripe(plan_key=plan_key)

        # Display results
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS(f"Successfully synced: {results['synced']} plan(s)"))
        if results["failed"] > 0:
            self.stdout.write(self.style.WARNING(f"Failed: {results['failed']} plan(s)"))
        if results["skipped"] > 0:
            self.stdout.write(self.style.WARNING(f"Skipped: {results['skipped']} plan(s)"))

        if results["errors"]:
            self.stdout.write("\nErrors:")
            for error in results["errors"]:
                self.stdout.write(self.style.ERROR(f"  - {error}"))

        self.stdout.write("\n" + "=" * 50)
