"""
Centralized utility for syncing subscription data from Stripe to database.
This ensures we always have up-to-date subscription information regardless of which page the user visits.
"""

from decimal import Decimal

from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.teams.models import Team
from sbomify.logging import getLogger

from .stripe_cache import CACHE_TTL, get_cached_subscription, invalidate_subscription_cache
from .stripe_client import StripeClient, StripeError

logger = getLogger(__name__)

# Initialize Stripe client
stripe_client = StripeClient()


def sync_subscription_from_stripe(team: Team, force_refresh: bool = False) -> bool:
    """
    Sync subscription data from Stripe to database.

    This function:
    1. Fetches latest subscription data from Stripe (with caching)
    2. Updates database if there are any changes
    3. Handles reactivation (cancellation reversal)
    4. Syncs next_billing_date if missing

    Args:
        team: Team instance to sync
        force_refresh: If True, bypasses cache and fetches fresh data

    Returns:
        True if sync was successful, False otherwise
    """
    billing_limits = team.billing_plan_limits or {}
    stripe_sub_id = billing_limits.get("stripe_subscription_id")

    if not stripe_sub_id:
        logger.debug("No subscription ID, skipping sync")
        return False

    logger.debug(f"Starting sync, force_refresh={force_refresh}")

    try:
        # Check if we should force refresh based on last update time
        # If last_updated is more than 1 minute ago, force refresh to catch recent cancellations
        last_updated_str = billing_limits.get("last_updated")
        should_force_refresh = force_refresh
        if not should_force_refresh and last_updated_str:
            try:
                from datetime import datetime

                last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                time_since_update = timezone.now() - last_updated.replace(tzinfo=timezone.utc)
                # Force refresh if last update was more than 1 minute ago
                if time_since_update.total_seconds() > 60:
                    should_force_refresh = True
                    logger.debug(f"Last update was {time_since_update.total_seconds()}s ago, forcing refresh")
            except (ValueError, AttributeError):
                pass  # If we can't parse, just use normal flow

        # Fetch subscription from Stripe (uses cache unless force_refresh)
        if should_force_refresh:
            # Force fresh fetch by invalidating cache first
            invalidate_subscription_cache(stripe_sub_id, team.key)
            subscription = stripe_client.get_subscription(stripe_sub_id)
            # Cache it for future use (skip caching MagicMock objects in tests)
            if subscription and not hasattr(subscription, "_mock_name"):
                from django.core.cache import cache

                cache_key = f"stripe_sub_{stripe_sub_id}_{team.key}"
                cache.set(cache_key, subscription, CACHE_TTL)
            logger.debug("Force refreshed subscription")
        else:
            subscription = get_cached_subscription(stripe_sub_id, team.key)
            if not subscription:
                # Cache miss, fetch fresh (get_cached_subscription already handles caching)
                subscription = stripe_client.get_subscription(stripe_sub_id)
                if subscription:
                    from django.core.cache import cache

                    cache_key = f"stripe_sub_{stripe_sub_id}_{team.key}"
                    cache.set(cache_key, subscription, CACHE_TTL)

        if not subscription:
            logger.warning("Could not fetch subscription")
            return False

        # Get current values from database
        current_sub_status = billing_limits.get("subscription_status")
        current_cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)
        current_next_billing_date = billing_limits.get("next_billing_date")

        # Get real-time values from Stripe
        # Use getattr with explicit False default to handle cases where attribute might not exist
        real_sub_status = getattr(subscription, "status", None) or current_sub_status
        # Explicitly check for cancel_at_period_end - it might be None, False, or True
        raw_cancel_at_period_end = getattr(subscription, "cancel_at_period_end", False)
        # Also check cancel_at - if it's set, subscription is scheduled to cancel
        cancel_at = getattr(subscription, "cancel_at", None)
        # Start with the raw value
        real_cancel_at_period_end = bool(raw_cancel_at_period_end)
        # If cancel_at is set (has a timestamp), treat it as scheduled for cancellation
        # This handles cases where cancel_at_period_end might be False but cancel_at is set
        # Handle MagicMock in tests - only override if cancel_at is a real numeric value
        if cancel_at is not None:
            cancel_at_value = None
            # Check if it's a numeric type (int, float)
            if isinstance(cancel_at, (int, float)):
                cancel_at_value = cancel_at
            else:
                # Try to convert MagicMock or other types
                try:
                    cancel_at_value = int(cancel_at)
                except (TypeError, ValueError, AttributeError):
                    # Can't convert, treat as not set - use raw_cancel_at_period_end
                    pass
            # Only override if we got a valid numeric value > 0
            if cancel_at_value is not None and cancel_at_value > 0:
                real_cancel_at_period_end = True
                logger.debug("cancel_at is set, treating as scheduled cancellation")

        logger.debug("Checking cancel status")

        # Log for debugging
        if real_cancel_at_period_end != current_cancel_at_period_end:
            logger.info("Cancel status change detected")

        # Check if we need to update
        needs_update = False
        updated_fields = []

        # Check subscription status
        if real_sub_status != current_sub_status:
            billing_limits["subscription_status"] = real_sub_status
            needs_update = True
            updated_fields.append("subscription_status")

            # If status changed to past_due, set payment_failed_at if not already set
            if real_sub_status == "past_due" and not billing_limits.get("payment_failed_at"):
                billing_limits["payment_failed_at"] = timezone.now().isoformat()
                updated_fields.append("payment_failed_at")
                logger.info("Payment failure detected, setting payment_failed_at")

            # If status changed from past_due to active/trialing, clear payment_failed_at
            elif current_sub_status == "past_due" and real_sub_status in ["active", "trialing"]:
                billing_limits.pop("payment_failed_at", None)
                updated_fields.append("payment_failed_at (cleared)")
                logger.info("Payment restored, clearing payment_failed_at")

        # Check cancel_at_period_end
        if real_cancel_at_period_end != current_cancel_at_period_end:
            billing_limits["cancel_at_period_end"] = real_cancel_at_period_end
            needs_update = True
            updated_fields.append("cancel_at_period_end")

            # Handle cancellation (new cancellation detected)
            if not current_cancel_at_period_end and real_cancel_at_period_end:
                # User just cancelled subscription - set scheduled_downgrade_plan if not already set
                # This handles cases where cancellation happens via Stripe portal directly
                if not billing_limits.get("scheduled_downgrade_plan"):
                    # Default to community plan for scheduled downgrade
                    billing_limits["scheduled_downgrade_plan"] = "community"
                    updated_fields.append("scheduled_downgrade_plan (set)")
                    logger.info("Detected cancellation, set scheduled_downgrade_plan to community")
                # Invalidate cache to ensure fresh data on next fetch
                invalidate_subscription_cache(stripe_sub_id, team.key)

            # Handle reactivation (cancellation reversal)
            elif current_cancel_at_period_end and not real_cancel_at_period_end:
                # User reactivated subscription - clear scheduled downgrade
                if billing_limits.get("scheduled_downgrade_plan"):
                    billing_limits.pop("scheduled_downgrade_plan", None)
                    updated_fields.append("scheduled_downgrade_plan (cleared)")
                    logger.info("User reactivated subscription, cleared scheduled downgrade")

        # Sync next_billing_date - always update to ensure it's correct
        # Use cancel_at if subscription is scheduled to cancel, otherwise use period_end
        next_billing_date = get_period_end_from_subscription(subscription, stripe_sub_id)
        if next_billing_date:
            # Update if it's different or missing (current_next_billing_date is None or empty)
            if not current_next_billing_date or next_billing_date != current_next_billing_date:
                billing_limits["next_billing_date"] = next_billing_date
                needs_update = True
                updated_fields.append("next_billing_date")
                logger.debug("Updated next_billing_date")

        # Update last_updated timestamp
        if needs_update:
            from django.db import transaction as db_transaction

            with db_transaction.atomic():
                # Use select_for_update to prevent race conditions
                team = Team.objects.select_for_update().get(pk=team.pk)
                billing_limits = team.billing_plan_limits or {}
                # Preserve existing customer_id and subscription_id to satisfy valid_billing_relationship constraint
                existing_customer_id = billing_limits.get("stripe_customer_id")
                existing_subscription_id = billing_limits.get("stripe_subscription_id")
                # Re-apply updates to ensure we have latest data
                for field in updated_fields:
                    if field == "subscription_status":
                        billing_limits["subscription_status"] = real_sub_status
                        # Also handle payment_failed_at when status changes
                        if real_sub_status == "past_due" and not billing_limits.get("payment_failed_at"):
                            billing_limits["payment_failed_at"] = timezone.now().isoformat()
                            logger.debug("Set payment_failed_at due to past_due status")
                        elif real_sub_status in ["active", "trialing"] and billing_limits.get("payment_failed_at"):
                            billing_limits.pop("payment_failed_at", None)
                            logger.debug("Cleared payment_failed_at due to restored status")
                    elif field == "payment_failed_at":
                        # Set payment_failed_at (already set above, but ensure it's in transaction)
                        if real_sub_status == "past_due":
                            billing_limits["payment_failed_at"] = timezone.now().isoformat()
                    elif field == "payment_failed_at (cleared)":
                        # Clear payment_failed_at
                        billing_limits.pop("payment_failed_at", None)
                    elif field == "cancel_at_period_end":
                        billing_limits["cancel_at_period_end"] = real_cancel_at_period_end
                        # Also handle scheduled_downgrade_plan when cancellation is detected
                        # This is a backup in case the "scheduled_downgrade_plan (set)" field wasn't processed
                        if real_cancel_at_period_end and not billing_limits.get("scheduled_downgrade_plan"):
                            billing_limits["scheduled_downgrade_plan"] = "community"
                            logger.info("Set scheduled_downgrade_plan in transaction")
                    elif field == "scheduled_downgrade_plan (set)":
                        billing_limits["scheduled_downgrade_plan"] = "community"
                        logger.debug("Applied scheduled_downgrade_plan (set)")
                    elif field == "scheduled_downgrade_plan (cleared)":
                        billing_limits.pop("scheduled_downgrade_plan", None)
                        logger.debug("Cleared scheduled_downgrade_plan")
                    elif field == "next_billing_date":
                        next_billing_date = get_period_end_from_subscription(subscription, stripe_sub_id)
                        if next_billing_date:
                            billing_limits["next_billing_date"] = next_billing_date

                billing_limits["last_updated"] = timezone.now().isoformat()
                # Ensure both customer_id and subscription_id are present or both absent (constraint requirement)
                # Preserve existing IDs if they were there before
                if existing_customer_id and not billing_limits.get("stripe_customer_id"):
                    billing_limits["stripe_customer_id"] = existing_customer_id
                if existing_subscription_id and not billing_limits.get("stripe_subscription_id"):
                    billing_limits["stripe_subscription_id"] = existing_subscription_id
                # If we have subscription_id, we must have customer_id (and vice versa)
                if billing_limits.get("stripe_subscription_id") and not billing_limits.get("stripe_customer_id"):
                    # Try to get customer_id from subscription if available
                    if hasattr(subscription, "customer"):
                        billing_limits["stripe_customer_id"] = subscription.customer
                    elif existing_customer_id:
                        billing_limits["stripe_customer_id"] = existing_customer_id
                    else:
                        # Can't satisfy constraint - remove subscription_id
                        logger.warning("Cannot satisfy valid_billing_relationship constraint, removing subscription_id")
                        billing_limits.pop("stripe_subscription_id", None)
                elif billing_limits.get("stripe_customer_id") and not billing_limits.get("stripe_subscription_id"):
                    # Have customer_id but no subscription_id - remove customer_id to satisfy constraint
                    logger.warning("Cannot satisfy valid_billing_relationship constraint, removing customer_id")
                    billing_limits.pop("stripe_customer_id", None)
                team.billing_plan_limits = billing_limits
                team.save()

                logger.info(f"Synced subscription data: {', '.join(updated_fields)}")
            return True

        return True  # No update needed, but sync was successful

    except StripeError as e:
        error_str = str(e).lower()
        # Handle deleted subscriptions
        if "no such subscription" in error_str or "resource_missing" in error_str:
            logger.info("Subscription no longer exists in Stripe")
            # Update database to reflect deleted subscription
            from django.db import transaction as db_transaction

            with db_transaction.atomic():
                team = Team.objects.select_for_update().get(pk=team.pk)
                billing_limits = team.billing_plan_limits or {}
                billing_limits["subscription_status"] = "canceled"
                billing_limits.pop("stripe_subscription_id", None)
                # Also remove customer_id to satisfy valid_billing_relationship constraint
                billing_limits.pop("stripe_customer_id", None)
                billing_limits.pop("scheduled_downgrade_plan", None)
                billing_limits["cancel_at_period_end"] = False
                billing_limits["last_updated"] = timezone.now().isoformat()
                team.billing_plan_limits = billing_limits
                team.save()
            invalidate_subscription_cache(stripe_sub_id, team.key)
            return True
        else:
            logger.warning(f"Failed to sync subscription: {e}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error syncing subscription: {e}")
        return False


def get_period_end_from_subscription(subscription, subscription_id: str) -> str | None:
    """
    Extract period_end from subscription object, trying multiple methods.

    Priority:
    1. If cancel_at is set (subscription scheduled to cancel), use cancel_at
    2. Otherwise, use current_period_end from subscription (dict or attribute access)
    3. If not available, try to get from upcoming invoice (for next billing date)
    4. As last resort, use period_end from latest invoice (but this is past period)

    Uses StripeClient to avoid direct stripe.api_key assignment.

    Returns:
        ISO format datetime string or None
    """
    import datetime
    from datetime import timezone as dt_timezone

    period_end = None

    # Priority 1: If subscription is scheduled to cancel, use cancel_at
    cancel_at = getattr(subscription, "cancel_at", None)
    if not cancel_at and isinstance(subscription, dict):
        cancel_at = subscription.get("cancel_at")
    if cancel_at:
        # Handle MagicMock in tests - check if it's a numeric type
        if not isinstance(cancel_at, (int, float)):
            try:
                cancel_at = int(cancel_at)
            except (TypeError, ValueError, AttributeError):
                # Can't convert, treat as not set
                cancel_at = None
        if cancel_at and cancel_at > 0:
            period_end = cancel_at
            logger.debug("Using cancel_at as period_end")

    # Priority 2: Try to get current_period_end from subscription
    # Try both attribute access and dictionary access
    if not period_end:
        period_end = getattr(subscription, "current_period_end", None)
        if not period_end and isinstance(subscription, dict):
            period_end = subscription.get("current_period_end")
        if period_end:
            logger.debug("Using current_period_end")

    # Priority 3: Calculate from billing_cycle_anchor and interval if current_period_end is not available
    if not period_end:
        try:
            billing_cycle_anchor = getattr(subscription, "billing_cycle_anchor", None)
            if not billing_cycle_anchor:
                # Try dictionary access
                if hasattr(subscription, "__getitem__"):
                    try:
                        billing_cycle_anchor = subscription["billing_cycle_anchor"]
                    except (KeyError, TypeError):
                        pass  # Expected if data missing

            logger.debug("Priority 3: billing_cycle_anchor found")

            if billing_cycle_anchor:
                # Get subscription items to find the billing interval
                # Note: subscription.items is a built-in method, so we must use dictionary access
                items = None
                if hasattr(subscription, "__getitem__"):
                    try:
                        items = subscription["items"]
                    except (KeyError, TypeError):
                        pass  # Expected if data missing

                logger.debug("Priority 3: items found")

                if items:
                    # Handle both StripeList and regular list
                    if hasattr(items, "data"):
                        items_list = items.data
                    elif isinstance(items, list):
                        items_list = items
                    else:
                        items_list = [items]

                    logger.debug(f"Priority 3: items_list length={len(items_list)}")

                    # Get interval from first item's price
                    for item in items_list:
                        price = getattr(item, "price", None) if not isinstance(item, dict) else item.get("price")
                        if price:
                            recurring = (
                                getattr(price, "recurring", None)
                                if not isinstance(price, dict)
                                else price.get("recurring")
                            )
                            if recurring:
                                interval = (
                                    getattr(recurring, "interval", None)
                                    if not isinstance(recurring, dict)
                                    else recurring.get("interval")
                                )
                                interval_count = (
                                    getattr(recurring, "interval_count", 1)
                                    if not isinstance(recurring, dict)
                                    else recurring.get("interval_count", 1)
                                )

                                if interval:
                                    # Calculate next billing date from anchor
                                    anchor_date = datetime.datetime.fromtimestamp(
                                        billing_cycle_anchor, tz=dt_timezone.utc
                                    )
                                    now = datetime.datetime.now(dt_timezone.utc)

                                    # Calculate how many intervals have passed
                                    if interval == "month":
                                        # Approximate: 30 days per month
                                        days_since_anchor = (now - anchor_date).days
                                        months_passed = days_since_anchor // 30
                                        next_anchor = anchor_date + datetime.timedelta(
                                            days=30 * (months_passed + 1) * interval_count
                                        )
                                    elif interval == "year":
                                        days_since_anchor = (now - anchor_date).days
                                        years_passed = days_since_anchor // 365
                                        next_anchor = anchor_date + datetime.timedelta(
                                            days=365 * (years_passed + 1) * interval_count
                                        )
                                    else:
                                        # Default to monthly
                                        days_since_anchor = (now - anchor_date).days
                                        months_passed = days_since_anchor // 30
                                        next_anchor = anchor_date + datetime.timedelta(
                                            days=30 * (months_passed + 1) * interval_count
                                        )

                                    period_end = int(next_anchor.timestamp())
                                    logger.info("Calculated period_end from billing_cycle_anchor")
                                    break
        except Exception as e:
            logger.warning(
                f"Could not calculate period_end from billing_cycle_anchor for subscription: {e}",
                exc_info=True,
            )

    # Priority 4: As last resort, try to get from latest invoice (but this is the past period end)
    if not period_end:
        try:
            invoices = stripe_client.stripe.Invoice.list(subscription=subscription_id, limit=1)
            if invoices.data and hasattr(invoices.data[0], "period_end") and invoices.data[0].period_end:
                # This is the period_end of the last invoice, which is in the past
                # We should add the billing interval to get the next billing date
                # But for now, let's just use it as a fallback and log a warning
                period_end = invoices.data[0].period_end
                logger.warning(
                    "Using latest invoice period_end. This may be a past date. Consider using upcoming invoice instead."
                )
        except Exception as e:
            logger.debug(f"Could not get period_end from invoice: {e}")

    if period_end:
        period_end_date = datetime.datetime.fromtimestamp(period_end, tz=dt_timezone.utc)
        return period_end_date.isoformat()

    return None


def _find_stripe_product_and_prices(plan: BillingPlan) -> tuple:
    """
    Find Stripe product and prices for a plan (read-only from Stripe).

    Args:
        plan: BillingPlan instance

    Returns:
        Tuple of (product_id, monthly_price_id, annual_price_id) or (None, None, None) if not found
    """
    try:
        # Find product - try stored ID first
        product = None
        if plan.stripe_product_id:
            try:
                product = stripe_client.stripe.Product.retrieve(plan.stripe_product_id)
                logger.debug(f"Found existing product {product.id} for plan {plan.key}")
            except StripeError:
                logger.debug(f"Product {plan.stripe_product_id} not found in Stripe")

        if not product:
            # Try to find by name (case-insensitive match)
            products = stripe_client.stripe.Product.list(active=True, limit=100).data
            product_match = next((p for p in products if p.name.lower() == plan.name.lower()), None)
            if product_match:
                product = product_match
                logger.debug(f"Found product by name {product.id} for plan {plan.key}")
            else:
                logger.warning(f"No matching Stripe product found for plan {plan.key}")
                return (None, None, None)

        # Get existing prices for this product, sorted by creation date (oldest first)
        # This ensures we pick the original/canonical price if duplicates exist
        existing_prices = sorted(
            stripe_client.stripe.Price.list(product=product.id, active=True, limit=100).data,
            key=lambda p: getattr(p, "created", 0) or 0,
        )

        monthly_price_id = plan.stripe_price_monthly_id
        annual_price_id = plan.stripe_price_annual_id

        # Find monthly price from Stripe (Stripe is source of truth - read only)
        # Takes the oldest monthly price (most stable/canonical)
        if not monthly_price_id:
            monthly_price = next(
                (p for p in existing_prices if p.recurring and p.recurring.interval == "month"),
                None,
            )

            if monthly_price:
                monthly_price_id = monthly_price.id
                amount = monthly_price.unit_amount / 100 if monthly_price.unit_amount else 0
                logger.debug(f"Found monthly price {monthly_price_id} (${amount}) for plan {plan.key}")
            else:
                logger.warning(f"No monthly price found in Stripe for plan {plan.key}")

        # Find annual price from Stripe (Stripe is source of truth - read only)
        # Takes the oldest annual price (most stable/canonical)
        if not annual_price_id:
            annual_price = next(
                (p for p in existing_prices if p.recurring and p.recurring.interval == "year"),
                None,
            )

            if annual_price:
                annual_price_id = annual_price.id
                amount = annual_price.unit_amount / 100 if annual_price.unit_amount else 0
                logger.debug(f"Found annual price {annual_price_id} (${amount}) for plan {plan.key}")
            else:
                logger.warning(f"No annual price found in Stripe for plan {plan.key}")

        return (product.id, monthly_price_id, annual_price_id)

    except StripeError as e:
        logger.error(f"Error finding/creating Stripe product/prices for plan {plan.key}: {e}")
        return (None, None, None)
    except Exception as e:
        logger.error(f"Unexpected error finding/creating Stripe product/prices for plan {plan.key}: {e}")
        return (None, None, None)


def sync_plan_prices_from_stripe(plan_key: str = None) -> dict:
    """
    Sync plan prices from Stripe to database.

    This function:
    1. Fetches all BillingPlan objects (or a specific plan if plan_key is provided)
    2. For plans without Stripe IDs but with prices, finds or creates Stripe products/prices
    3. For each plan with Stripe price IDs, fetches the current price from Stripe
    4. Updates monthly_price and annual_price fields in the database
    5. Updates last_synced_at timestamp

    Args:
        plan_key: Optional plan key to sync a specific plan. If None, syncs all plans.

    Returns:
        Dictionary with sync results: {
            'synced': int,  # Number of plans successfully synced
            'failed': int,  # Number of plans that failed to sync
            'skipped': int,  # Number of plans skipped (no prices and no Stripe IDs)
            'errors': list   # List of error messages
        }
    """
    from django.db import transaction

    results = {"synced": 0, "failed": 0, "skipped": 0, "errors": []}

    # Get plans to sync
    if plan_key:
        plans = BillingPlan.objects.filter(key=plan_key)
    else:
        # Sync all plans except community (which doesn't have Stripe prices)
        plans = BillingPlan.objects.exclude(key=BillingPlan.KEY_COMMUNITY)

    logger.info(f"Starting price sync for {plans.count()} plan(s)")

    for plan in plans:
        try:
            logger.debug(f"Processing plan {plan.key}")

            # Check if plan needs Stripe IDs (either has prices but no IDs, or no prices and no IDs - "fresh start")
            # We want to try finding/creating Stripe objects for any plan that lacks IDs
            has_stripe_ids = plan.stripe_price_monthly_id or plan.stripe_price_annual_id

            if not has_stripe_ids:
                logger.info(f"Plan {plan.key} has no Stripe IDs, attempting to find or create Stripe product/prices")
                product_id, monthly_id, annual_id = _find_stripe_product_and_prices(plan)
                if product_id:
                    # Update plan with Stripe IDs AND fetch prices from Stripe
                    # We must set prices before saving to pass validation
                    with transaction.atomic():
                        plan._skip_team_update = True
                        plan.stripe_product_id = product_id
                        update_fields = ["stripe_product_id"]

                        if monthly_id:
                            plan.stripe_price_monthly_id = monthly_id
                            update_fields.append("stripe_price_monthly_id")
                            try:
                                monthly_stripe_price = stripe_client.get_price(monthly_id)
                                if monthly_stripe_price and monthly_stripe_price.unit_amount is not None:
                                    plan.monthly_price = Decimal(monthly_stripe_price.unit_amount) / Decimal("100")
                                    update_fields.append("monthly_price")
                                    logger.debug(f"Set monthly_price to ${plan.monthly_price} from Stripe")
                                else:
                                    logger.warning(
                                        f"Stripe monthly price {monthly_id} has no amount. "
                                        f"Preserving existing monthly price: "
                                        f"${plan.monthly_price}"
                                    )
                            except StripeError as e:
                                logger.warning(
                                    f"Could not fetch monthly price for {monthly_id}: {e}. "
                                    f"Preserving existing monthly price: "
                                    f"${plan.monthly_price}"
                                )
                                # Do not update monthly_price - preserve existing value

                        if annual_id:
                            plan.stripe_price_annual_id = annual_id
                            update_fields.append("stripe_price_annual_id")
                            try:
                                annual_stripe_price = stripe_client.get_price(annual_id)
                                if annual_stripe_price and annual_stripe_price.unit_amount is not None:
                                    plan.annual_price = Decimal(annual_stripe_price.unit_amount) / Decimal("100")
                                    update_fields.append("annual_price")
                                    logger.debug(f"Set annual_price to ${plan.annual_price} from Stripe")
                                else:
                                    logger.warning(
                                        f"Stripe annual price {annual_id} has no amount. "
                                        f"Preserving existing annual price: "
                                        f"${plan.annual_price}"
                                    )
                            except StripeError as e:
                                logger.warning(
                                    f"Could not fetch annual price for {annual_id}: {e}. "
                                    f"Preserving existing annual price: "
                                    f"${plan.annual_price}"
                                )
                                # Do not update annual_price - preserve existing value

                        plan.save(update_fields=update_fields)
                        logger.info(f"Updated plan {plan.key} with Stripe IDs")
                    # Refresh plan from DB to get updated IDs
                    plan.refresh_from_db()
                    # Recalculate has_stripe_ids after refresh
                    has_stripe_ids = plan.stripe_price_monthly_id or plan.stripe_price_annual_id
                else:
                    # If we couldn't find/create product, we can't do anything else
                    # IMPORTANT: Do not clear prices - preserve existing values
                    error_msg = f"Failed to find or create Stripe product/prices for plan {plan.key}"
                    logger.warning(
                        f"{error_msg}. Preserving existing prices: "
                        f"monthly=${plan.monthly_price}, "
                        f"annual=${plan.annual_price}"
                    )
                    results["errors"].append(error_msg)
                    results["failed"] += 1
                    continue

            # Skip plans that still have no Stripe IDs
            # IMPORTANT: Do not clear prices when Stripe IDs are missing - preserve existing prices
            if not has_stripe_ids:
                logger.debug(
                    f"Skipping plan {plan.key}: could not resolve Stripe price IDs. "
                    f"Preserving existing prices: monthly=${plan.monthly_price}, "
                    f"annual=${plan.annual_price}"
                )
                results["skipped"] += 1
                continue

            updated = False
            price_updates = {}

            # Sync monthly price
            # IMPORTANT: Only update price if we successfully fetch it from Stripe
            # If fetch fails, preserve existing price - do not clear it
            if plan.stripe_price_monthly_id:
                try:
                    stripe_price = stripe_client.get_price(plan.stripe_price_monthly_id)
                    if stripe_price and stripe_price.unit_amount is not None:
                        stripe_amount = Decimal(stripe_price.unit_amount) / Decimal("100")
                        # Compare with proper Decimal handling
                        current_price = Decimal(str(plan.monthly_price)) if plan.monthly_price is not None else None
                        if current_price is None or abs(current_price - stripe_amount) > Decimal("0.01"):
                            price_updates["monthly_price"] = stripe_amount
                            updated = True
                            logger.info(f"Plan {plan.key}: monthly price update: ${current_price} -> ${stripe_amount}")
                        else:
                            logger.debug(f"Plan {plan.key}: monthly price already matches: ${stripe_amount}")
                    else:
                        logger.warning(
                            f"Plan {plan.key}: Stripe monthly price "
                            f"{plan.stripe_price_monthly_id} has no amount. "
                            f"Preserving existing price: ${plan.monthly_price}"
                        )
                except StripeError as e:
                    error_msg = f"Failed to fetch monthly price for plan {plan.key}: {e}"
                    logger.warning(f"{error_msg}. Preserving existing monthly price: ${plan.monthly_price}")
                    results["errors"].append(error_msg)
                    # Do not update price - preserve existing value

            # Sync annual price
            # IMPORTANT: Only update price if we successfully fetch it from Stripe
            # If fetch fails, preserve existing price - do not clear it
            if plan.stripe_price_annual_id:
                try:
                    stripe_price = stripe_client.get_price(plan.stripe_price_annual_id)
                    if stripe_price and stripe_price.unit_amount is not None:
                        stripe_amount = Decimal(stripe_price.unit_amount) / Decimal("100")
                        # Compare with proper Decimal handling
                        current_price = Decimal(str(plan.annual_price)) if plan.annual_price is not None else None
                        if current_price is None or abs(current_price - stripe_amount) > Decimal("0.01"):
                            price_updates["annual_price"] = stripe_amount
                            updated = True
                            logger.info(f"Plan {plan.key}: annual price update: ${current_price} -> ${stripe_amount}")
                        else:
                            logger.debug(f"Plan {plan.key}: annual price already matches: ${stripe_amount}")
                    else:
                        logger.warning(
                            f"Plan {plan.key}: Stripe annual price "
                            f"{plan.stripe_price_annual_id} has no amount. "
                            f"Preserving existing price: ${plan.annual_price}"
                        )
                except StripeError as e:
                    error_msg = f"Failed to fetch annual price for plan {plan.key}: {e}"
                    logger.warning(f"{error_msg}. Preserving existing annual price: ${plan.annual_price}")
                    results["errors"].append(error_msg)
                    # Do not update price - preserve existing value

            # Always update last_synced_at, and update prices if they changed
            with transaction.atomic():
                # Use update_fields to skip team updates during price sync
                plan._skip_team_update = True
                for field, value in price_updates.items():
                    setattr(plan, field, value)
                plan.last_synced_at = timezone.now()

                # Build update_fields list
                update_fields = ["last_synced_at"]
                if price_updates:
                    update_fields.extend(price_updates.keys())

                plan.save(update_fields=update_fields)

                if updated:
                    logger.info(f"Successfully synced prices for plan {plan.key}")
                else:
                    logger.info(
                        f"Plan {plan.key}: prices already up to date "
                        f"(monthly=${plan.monthly_price}, annual=${plan.annual_price})"
                    )
                results["synced"] += 1

        except Exception as e:
            error_msg = f"Unexpected error syncing prices for plan {plan.key}: {e}"
            logger.error(error_msg)
            results["errors"].append(error_msg)
            results["failed"] += 1

    logger.info(
        f"Price sync completed: {results['synced']} synced, {results['failed']} failed, {results['skipped']} skipped"
    )
    return results
