import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import BillingPlan
from .stripe_client import StripeClient, StripeError
from .utils import CACHE_TTL_HOURS

logger = logging.getLogger(__name__)


class StripePricingService:
    """Service for fetching and formatting pricing data from Stripe."""

    # Cache TTL for pricing data
    CACHE_TTL = timedelta(hours=CACHE_TTL_HOURS)

    def __init__(self):
        self.stripe_client = StripeClient()

    def get_all_plans_pricing(self, force_refresh: bool = False):
        """
        Fetch all billing plans and enrich them with current pricing from Stripe.
        Returns a dictionary mapping plan keys to their pricing details.

        Implements a cache mechanism:
        1. Checks if DB plans have been synced recently (TTL 1 hour).
        2. If fresh and not force_refresh, returns data from DB.
        3. If stale or force_refresh, fetches from Stripe, updates DB, and returns new data.

        On Stripe API failure, returns cached data from DB instead of empty dict.
        """
        # Get all database plans first (excluding community which has no Stripe pricing)
        db_plans = list(BillingPlan.objects.exclude(key="community"))

        if not db_plans:
            return {}

        # Check if we can use cached data
        now = timezone.now()
        needs_refresh = force_refresh

        if not needs_refresh:
            for plan in db_plans:
                if not plan.last_synced_at or (now - plan.last_synced_at) > self.CACHE_TTL:
                    needs_refresh = True
                    break

        if not needs_refresh:
            return self._build_pricing_from_db(db_plans)

        # Fetch from Stripe and update DB
        try:
            return self._refresh_pricing_from_stripe(db_plans)
        except StripeError as e:
            logger.error(f"Failed to fetch Stripe products: {e}. Returning cached data.")
            # Check cache staleness - fail if cache is too old (24 hours)
            stale_threshold = timedelta(hours=24)
            for plan in db_plans:
                if plan.last_synced_at:
                    age = timezone.now() - plan.last_synced_at
                    if age > stale_threshold:
                        logger.warning(
                            f"Pricing cache for plan {plan.key} is stale ({age}). "
                            f"Stripe sync failed. Consider investigating Stripe API issues."
                        )
            return self._build_pricing_from_db(db_plans)

    def _build_pricing_from_db(self, db_plans):
        """Build pricing dict from database plans (cached data)."""
        plans_pricing = {}

        for plan in db_plans:
            pricing = {
                "monthly_price": plan.monthly_price,
                "annual_price": plan.annual_price,
                "monthly_id": plan.stripe_price_monthly_id,
                "annual_id": plan.stripe_price_annual_id,
                "discount_percent_monthly": plan.discount_percent_monthly,
                "discount_percent_annual": plan.discount_percent_annual,
                "savings": plan.annual_savings,
                "monthly_price_annualized": None,
                "monthly_price_discounted": plan.monthly_price_discounted,
                "annual_price_discounted": plan.annual_price_discounted,
            }

            if pricing["monthly_price"]:
                pricing["monthly_price_annualized"] = pricing["monthly_price"] * 12

            if plan.annual_vs_monthly_savings and plan.annual_vs_monthly_savings > 0:
                pricing["savings"] = plan.annual_vs_monthly_savings
                if pricing["monthly_price"]:
                    monthly_annualized = pricing["monthly_price"] * 12
                    if monthly_annualized > 0:
                        savings_percent = (plan.annual_vs_monthly_savings / monthly_annualized) * 100
                        pricing["annual_savings_percent"] = round(float(savings_percent), 1)

            plans_pricing[plan.key] = pricing

        return plans_pricing

    def _refresh_pricing_from_stripe(self, db_plans):
        """
        Refresh pricing from Stripe API and update database.

        Fetches Stripe data outside transaction to avoid holding locks during API calls.
        Uses select_for_update only for the final database update to prevent race conditions.
        """
        plan_keys = [p.key for p in db_plans]

        # Fetch all products and prices from Stripe OUTSIDE transaction
        # This prevents holding database locks during potentially slow API calls
        try:
            stripe_products = self.stripe_client.get_all_products_with_prices()
        except StripeError as e:
            logger.error(f"Failed to fetch Stripe products: {e}")
            raise

        # Process Stripe data into pricing dicts
        plans_pricing = {}
        pricing_updates = {}  # Store updates to apply in transaction

        for db_plan in db_plans:
            # Find matching Stripe product
            stripe_data = next(
                (item for item in stripe_products if item["product"].id == db_plan.stripe_product_id), None
            )

            pricing = self._process_stripe_data(db_plan, stripe_data)
            plans_pricing[db_plan.key] = pricing

            # Store updates for this plan
            pricing_updates[db_plan.key] = {
                "monthly_price": pricing["monthly_price"],
                "annual_price": pricing["annual_price"],
                "stripe_price_monthly_id": pricing["monthly_id"],
                "stripe_price_annual_id": pricing["annual_id"],
                "discount_percent_monthly": int(pricing["discount_percent_monthly"]),
                "discount_percent_annual": int(pricing["discount_percent_annual"]),
            }

        # Now update database in a short transaction with locks
        with transaction.atomic():
            locked_plans = BillingPlan.objects.select_for_update().filter(key__in=plan_keys)

            for db_plan in locked_plans:
                if db_plan.key not in pricing_updates:
                    logger.warning(f"No pricing data found for plan {db_plan.key}")
                    continue

                updates = pricing_updates[db_plan.key]

                # Update DB with synced data - use _skip_team_update to prevent signal cascade
                db_plan._skip_team_update = True
                db_plan.monthly_price = updates["monthly_price"]
                db_plan.annual_price = updates["annual_price"]
                db_plan.stripe_price_monthly_id = updates["stripe_price_monthly_id"]
                db_plan.stripe_price_annual_id = updates["stripe_price_annual_id"]
                db_plan.discount_percent_monthly = updates["discount_percent_monthly"]
                db_plan.discount_percent_annual = updates["discount_percent_annual"]
                db_plan.last_synced_at = timezone.now()

                try:
                    db_plan.save(
                        update_fields=[
                            "monthly_price",
                            "annual_price",
                            "stripe_price_monthly_id",
                            "stripe_price_annual_id",
                            "discount_percent_monthly",
                            "discount_percent_annual",
                            "last_synced_at",
                        ]
                    )
                except Exception as e:
                    logger.error(f"Failed to save synced plan data for {db_plan.key}: {e}", exc_info=True)
                    # Continue with other plans even if one fails

        return plans_pricing

    def _process_stripe_data(self, db_plan, stripe_data):
        """Process Stripe product/price data into pricing dict."""
        pricing = {
            "monthly_price": None,
            "annual_price": None,
            "monthly_id": None,
            "annual_id": None,
            "discount_percent_monthly": 0,
            "discount_percent_annual": 0,
            "savings": None,
            "monthly_price_discounted": None,
            "annual_price_discounted": None,
        }

        if not stripe_data:
            return pricing

        prices = stripe_data["prices"]
        product_metadata = stripe_data["product"].metadata

        # Find monthly price
        monthly = next((p for p in prices if p.recurring and p.recurring.interval == "month"), None)
        if monthly and monthly.unit_amount is not None:
            pricing["monthly_price"] = Decimal(monthly.unit_amount) / Decimal("100")
            pricing["monthly_id"] = monthly.id
            pricing["monthly_price_base_annualized"] = pricing["monthly_price"] * Decimal("12")

        # Find annual price
        annual = next((p for p in prices if p.recurring and p.recurring.interval == "year"), None)
        if annual and annual.unit_amount is not None:
            pricing["annual_price"] = Decimal(annual.unit_amount) / Decimal("100")
            pricing["annual_id"] = annual.id

        # Check for explicit discount metadata - use Decimal for consistency
        if "monthly_discount_percent" in product_metadata:
            try:
                pricing["discount_percent_monthly"] = float(Decimal(str(product_metadata["monthly_discount_percent"])))
            except (ValueError, TypeError, Exception):
                logger.warning(f"Invalid monthly_discount_percent for plan {db_plan.key}")
                pricing["discount_percent_monthly"] = 0

        if "annual_discount_percent" in product_metadata:
            try:
                pricing["discount_percent_annual"] = float(Decimal(str(product_metadata["annual_discount_percent"])))
            except (ValueError, TypeError, Exception):
                logger.warning(f"Invalid annual_discount_percent for plan {db_plan.key}")
                pricing["discount_percent_annual"] = 0

        # Check for promotional message
        if "promo_message" in product_metadata:
            pricing["promo_message"] = product_metadata["promo_message"]

        # Check for coupon IDs
        if "monthly_coupon_id" in product_metadata:
            pricing["monthly_coupon_id"] = product_metadata["monthly_coupon_id"]
        if "annual_coupon_id" in product_metadata:
            pricing["annual_coupon_id"] = product_metadata["annual_coupon_id"]

        # Calculate discounted prices - use Decimal throughout for precision
        pricing["monthly_price_discounted"] = pricing["monthly_price"]
        if pricing["discount_percent_monthly"] > 0 and pricing["monthly_price"] is not None:
            discount_factor = Decimal("1") - (Decimal(str(pricing["discount_percent_monthly"])) / Decimal("100"))
            pricing["monthly_price_discounted"] = pricing["monthly_price"] * discount_factor

        pricing["annual_price_discounted"] = pricing["annual_price"]
        if pricing["discount_percent_annual"] > 0 and pricing["annual_price"] is not None:
            discount_factor = Decimal("1") - (Decimal(str(pricing["discount_percent_annual"])) / Decimal("100"))
            pricing["annual_price_discounted"] = pricing["annual_price"] * discount_factor

        # Calculate annual savings (monthly*12 vs annual) - use Decimal
        if pricing["monthly_price"] is not None and pricing["annual_price"] is not None:
            monthly_annualized_base = pricing["monthly_price"] * Decimal("12")
            savings_base = monthly_annualized_base - pricing["annual_price"]

            if savings_base > 0:
                pricing["savings"] = savings_base
                if monthly_annualized_base > 0:
                    savings_percent = (savings_base / monthly_annualized_base) * Decimal("100")
                    pricing["annual_savings_percent"] = round(float(savings_percent), 1)

        # Calculate total annual savings (base monthly × 12 - discounted annual price)
        if (
            pricing.get("monthly_price_base_annualized") is not None
            and pricing.get("annual_price_discounted") is not None
        ):
            total_savings = pricing["monthly_price_base_annualized"] - pricing["annual_price_discounted"]
            if total_savings > 0:
                pricing["total_annual_savings"] = total_savings

        if pricing["monthly_price_discounted"] is not None:
            pricing["monthly_price_annualized"] = pricing["monthly_price_discounted"] * Decimal("12")

        return pricing

    def create_checkout_session(self, team, user_email, plan, billing_period, success_url, cancel_url, coupon_id=None):
        """
        Create a Stripe checkout session for a team.
        Handles customer creation if needed.

        Note: This method ensures the valid_billing_relationship constraint is satisfied.
        The constraint requires both stripe_customer_id and stripe_subscription_id to be set together,
        or both to be null. Since we don't have a subscription_id yet, we cannot save the customer_id
        to the database. The customer_id will be saved atomically with the subscription_id when
        checkout completes (in billing_processing.handle_checkout_completed).
        """

        billing_limits = team.billing_plan_limits or {}
        customer_id = billing_limits.get("stripe_customer_id")

        if not customer_id:
            try:
                # Create customer in Stripe first
                customer = self.stripe_client.create_customer(
                    email=user_email, name=team.name, metadata={"team_key": team.key}
                )
                customer_id = customer.id

                # We cannot save customer_id to DB here because valid_billing_relationship constraint
                # requires both customer_id and subscription_id to be set together.
                # This is safe because:
                # 1. If checkout succeeds, handle_checkout_completed will save both IDs atomically
                # 2. If checkout fails/cancels, Stripe customer exists but is unused (orphaned customer)
                # 3. We can clean up orphaned customers periodically with a maintenance script
                # 4. The constraint ensures we never have a customer_id without subscription_id in DB

                logger.debug(
                    f"Created Stripe customer {customer_id} for team {team.key}. "
                    f"Will save to DB when checkout completes."
                )
            except Exception as e:
                logger.error(f"Failed to create Stripe customer for team {team.key}: {e}")
                raise StripeError(f"Failed to create customer: {str(e)}")

        # Determine price ID
        price_id = plan.stripe_price_monthly_id if billing_period == "monthly" else plan.stripe_price_annual_id
        if not price_id:
            logger.error(f"Missing price ID for plan {plan.key} ({billing_period})")
            raise StripeError("Configuration error: Missing price ID for selected plan")

        # Prepare session data
        session_data = {
            "customer": customer_id,
            "payment_method_types": ["card"],
            "line_items": [
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"team_key": team.key, "plan_key": plan.key},
            "allow_promotion_codes": True,
        }

        # Handle coupons - if implicit coupon provided, override allow_promotion_codes
        if coupon_id:
            session_data["discounts"] = [{"coupon": coupon_id}]
            # Cannot use allow_promotion_codes with discounts
            del session_data["allow_promotion_codes"]

        try:
            return self.stripe_client.stripe.checkout.Session.create(**session_data)
        except self.stripe_client.stripe.error.StripeError as e:
            logger.error(f"Stripe checkout error for team {team.key}: {e}")
            raise StripeError(f"Payment provider error: {str(e)}")
