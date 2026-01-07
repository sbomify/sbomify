"""
Service for calculating team pricing information for display.
"""

import logging
from typing import Any, Dict, Optional

from django.db import DatabaseError, OperationalError, transaction

from .models import BillingPlan
from .stripe_client import StripeClient, StripeError
from .stripe_pricing_service import StripePricingService

logger = logging.getLogger(__name__)


class TeamPricingService:
    """Service for calculating and formatting team pricing information."""

    def __init__(self):
        self.stripe_client = StripeClient()
        self.pricing_service = StripePricingService()

    def get_plan_pricing(self, team, billing_plan_obj: Optional[BillingPlan] = None) -> Dict[str, Any]:
        """
        Calculate pricing information for a team's billing plan.

        Args:
            team: Team instance
            billing_plan_obj: Optional BillingPlan instance (will be fetched if not provided)

        Returns:
            Dictionary with pricing information:
            {
                "amount": str,  # Formatted price string
                "period": str,  # "per month", "per year", "forever", etc.
                "billing_period": Optional[str],  # "monthly", "annual", or None
            }
        """
        billing_plan = team.billing_plan or "community"
        billing_plan_limits = team.billing_plan_limits or {}

        # Default fallback
        plan_pricing = {"amount": "Contact us", "period": "", "billing_period": None}

        # Fetch billing plan if not provided
        if billing_plan_obj is None:
            try:
                BillingPlan.objects.get(key=billing_plan)
            except BillingPlan.DoesNotExist:
                if billing_plan == "community":
                    return {"amount": "$0", "period": "forever", "billing_period": None}
                return plan_pricing

        # Extract billing period and payment info
        billing_period = billing_plan_limits.get("billing_period")
        last_payment_amount = billing_plan_limits.get("last_payment_amount")
        last_payment_currency = billing_plan_limits.get("last_payment_currency", "usd")
        stripe_subscription_id = billing_plan_limits.get("stripe_subscription_id")
        stripe_customer_id = billing_plan_limits.get("stripe_customer_id")
        next_billing_date = billing_plan_limits.get("next_billing_date")

        # Attempt to recover missing subscription ID if we have a customer ID
        if not stripe_subscription_id and stripe_customer_id and billing_plan in ["business", "enterprise"]:
            try:
                # List active subscriptions for the customer
                subscriptions = self.stripe_client.stripe.Subscription.list(
                    customer=stripe_customer_id, status="active", limit=1
                )
                if subscriptions and subscriptions.data:
                    stripe_subscription_id = subscriptions.data[0].id
                    # We will save this implicitly when we fetch invoice amount below if we update the limits
                    # But better to save it now or let the fetch mechanism handle it?
                    # valid_billing_relationship constraint requires both to be set.
                    # Let's rely on _fetch_invoice_amount to update the limits if we pass the ID.
            except StripeError as e:
                logger.error(f"Failed to recover subscription ID for team {team.key}: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error recovering subscription ID for team {team.key}: {e}")

        # Community plan is always free
        if billing_plan == "community":
            return {"amount": "$0", "period": "forever", "billing_period": None}

        # Sync subscription data from Stripe first to ensure we have latest status
        # Note: team might be a Pydantic schema, so we need to get the actual model instance
        if stripe_subscription_id:
            try:
                from sbomify.apps.teams.models import Team

                from .stripe_sync import sync_subscription_from_stripe

                # Get actual Team model instance if team is a schema
                if hasattr(team, "key") and not hasattr(team, "pk"):
                    # It's a Pydantic schema, fetch the model instance
                    team_obj = Team.objects.get(key=team.key)
                else:
                    # It's already a model instance
                    team_obj = team

                sync_subscription_from_stripe(team_obj)
                # Refresh billing_plan_limits after sync
                team_obj.refresh_from_db()
                billing_plan_limits = team_obj.billing_plan_limits or {}
                # Update local variables from refreshed data
                next_billing_date = billing_plan_limits.get("next_billing_date")
                last_payment_amount = billing_plan_limits.get("last_payment_amount")
                last_payment_currency = billing_plan_limits.get("last_payment_currency", "usd")
                # Also update team's billing_plan_limits if it's a schema
                if hasattr(team, "key") and not hasattr(team, "pk"):
                    # Update the schema object with synced data
                    team.billing_plan_limits = billing_plan_limits
            except Exception as e:
                logger.warning(f"Failed to sync subscription for pricing display: {e}")

        # Try to fetch invoice and date if we don't have them
        if (last_payment_amount is None or next_billing_date is None) and stripe_subscription_id:
            last_payment_amount, last_payment_currency, next_billing_date = self._fetch_invoice_amount(
                stripe_subscription_id, team
            )

        # Ensure next_billing_date is a datetime object for template formatting
        if next_billing_date:
            from datetime import datetime

            from django.utils import timezone as django_timezone

            if isinstance(next_billing_date, str):
                try:
                    # Try parsing ISO format string
                    next_billing_date = datetime.fromisoformat(next_billing_date.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    try:
                        # Try parsing as timestamp
                        next_billing_date = datetime.fromtimestamp(float(next_billing_date), tz=django_timezone.utc)
                    except (ValueError, TypeError):
                        logger.warning(f"Failed to parse next_billing_date: {next_billing_date}")
                        next_billing_date = None
            elif isinstance(next_billing_date, (int, float)):
                # Handle timestamp
                try:
                    next_billing_date = datetime.fromtimestamp(next_billing_date, tz=django_timezone.utc)
                except (ValueError, OSError):
                    logger.warning(f"Failed to convert timestamp to datetime: {next_billing_date}")
                    next_billing_date = None
            # Ensure timezone-aware
            if next_billing_date and next_billing_date.tzinfo is None:
                next_billing_date = django_timezone.make_aware(next_billing_date)

        # Use actual paid amount if available
        if last_payment_amount is not None:
            currency_symbol = "$" if last_payment_currency == "usd" else last_payment_currency.upper() + " "
            period_display = "per month" if billing_period == "monthly" else "per year"

            return {
                "amount": f"{currency_symbol}{last_payment_amount:.2f}",
                "period": period_display,
                "billing_period": billing_period,
                "next_billing_date": next_billing_date,
            }

        # Fall back to plan pricing from Stripe
        if billing_plan in ["business", "enterprise"]:
            pricing = self._get_plan_pricing_from_stripe(billing_plan, billing_period)
            if next_billing_date:
                pricing["next_billing_date"] = next_billing_date
            return pricing

        return plan_pricing

    def _fetch_invoice_amount(self, subscription_id: str, team) -> tuple[Optional[float], str, Optional[str]]:
        """
        Fetch invoice amount and next billing date from Stripe and cache it.

        Returns:
            Tuple of (amount, currency, next_billing_date)
        """
        try:
            subscription = self.stripe_client.get_subscription(subscription_id)

            # Get next billing date using centralized utility
            # This will use cancel_at if subscription is scheduled to cancel, otherwise period_end
            from .stripe_sync import get_period_end_from_subscription

            next_billing_date = get_period_end_from_subscription(subscription, subscription_id)

            # Get invoice amount (optional, wrap in try/except)
            amount = None
            currency = "usd"

            try:
                if subscription.latest_invoice:
                    if isinstance(subscription.latest_invoice, str):
                        invoice = self.stripe_client.get_invoice(subscription.latest_invoice)
                    else:
                        invoice = subscription.latest_invoice

                    amount = invoice.amount_paid / 100.0 if invoice.amount_paid else 0
                    currency = invoice.currency

                    # Update local variable if we found a valid amount (fallback logic in caller handles None)
                    if amount is None:
                        amount = 0.0  # Default if paid is None but invoice exists?
            except Exception as e:
                logger.warning(f"Failed to fetch invoice details for subscription {subscription_id}: {e}")

            # Cache what we found
            from sbomify.apps.teams.models import Team

            # Get actual Team model instance if team is a schema
            if hasattr(team, "key") and not hasattr(team, "pk"):
                # It's a Pydantic schema, fetch the model instance
                team_obj = Team.objects.get(key=team.key)
            else:
                # It's already a model instance
                team_obj = team

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with transaction.atomic():
                        locked_team = Team.objects.select_for_update().get(pk=team_obj.pk)
                        billing_plan_limits = locked_team.billing_plan_limits or {}

                        # Only update fields we have valid values for
                        if amount is not None:
                            billing_plan_limits["last_payment_amount"] = amount
                            billing_plan_limits["last_payment_currency"] = currency

                        if next_billing_date:
                            billing_plan_limits["next_billing_date"] = next_billing_date

                        billing_plan_limits["stripe_subscription_id"] = subscription_id

                        # Sync cancellation status (defaults to False if not present in subscription)
                        # We use getattr because the attribute might be top-level or handled differently in API versions
                        cancel_at_period_end = getattr(subscription, "cancel_at_period_end", False)
                        billing_plan_limits["cancel_at_period_end"] = cancel_at_period_end

                        locked_team.billing_plan_limits = billing_plan_limits
                        locked_team.save(update_fields=["billing_plan_limits"])
                        break
                except (DatabaseError, OperationalError) as db_error:
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to update limits: {db_error}")
                        # Don't raise, just return what we have so we display something
                        break
                    import time

                    time.sleep(0.1 * (attempt + 1))
                except Exception as e:
                    logger.error(f"Unexpected error updating limits: {e}")
                    break

            return amount, currency, next_billing_date

        except StripeError as e:
            logger.error(f"Failed to fetch subscription for team {team.key}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error fetching subscription for team {team.key}: {e}")

        return None, "usd", None

    def _get_plan_pricing_from_stripe(self, billing_plan: str, billing_period: Optional[str]) -> Dict[str, Any]:
        """Get pricing from Stripe pricing service."""
        try:
            stripe_pricing = self.pricing_service.get_all_plans_pricing(force_refresh=False)
            plan_stripe_data = stripe_pricing.get(billing_plan, {})

            monthly_discounted = plan_stripe_data.get("monthly_price_discounted")
            annual_discounted = plan_stripe_data.get("annual_price_discounted")

            if billing_period == "annual" and annual_discounted:
                return {
                    "amount": f"${float(annual_discounted):.0f}",
                    "period": "per year",
                    "billing_period": "annual",
                }
            elif billing_period == "monthly" and monthly_discounted:
                return {
                    "amount": f"${float(monthly_discounted):.0f}",
                    "period": "per month",
                    "billing_period": "monthly",
                }
            elif monthly_discounted:
                # Default to monthly if billing_period is not set
                return {
                    "amount": f"${float(monthly_discounted):.0f}",
                    "period": "per month",
                    "billing_period": None,
                }
            elif annual_discounted:
                return {
                    "amount": f"${float(annual_discounted):.0f}",
                    "period": "per year",
                    "billing_period": None,
                }
        except Exception as e:
            logger.error(f"Failed to get pricing from Stripe for plan {billing_plan}: {e}")

        return {"amount": "Custom", "period": "pricing", "billing_period": None}

    def get_plan_limits(self, team, billing_plan_obj: Optional[BillingPlan] = None) -> list:
        """
        Get formatted plan limits for display.

        Args:
            team: Team instance
            billing_plan_obj: Optional BillingPlan instance

        Returns:
            List of limit dictionaries with icon, label, and value
        """
        # Define PLAN_LIMITS locally to avoid circular import
        PLAN_LIMITS = {
            "max_products": {
                "label": "Products",
                "icon": "box",
            },
            "max_projects": {
                "label": "Projects",
                "icon": "project-diagram",
            },
            "max_components": {
                "label": "Components",
                "icon": "cube",
            },
        }

        plan_limits = []
        billing_plan_limits = team.billing_plan_limits or {}

        # Fetch billing plan if not provided
        if billing_plan_obj is None:
            billing_plan = team.billing_plan or "community"
            try:
                billing_plan_obj = BillingPlan.objects.get(key=billing_plan)
            except BillingPlan.DoesNotExist:
                billing_plan_obj = None

        if billing_plan_obj:
            # Build limits dict - prefer billing_plan_limits, fallback to model
            limits_dict = {}
            for limit_key in PLAN_LIMITS.keys():
                if limit_key in billing_plan_limits:
                    limits_dict[limit_key] = billing_plan_limits[limit_key]
                else:
                    # Direct attribute access instead of hasattr/getattr
                    limit_value = getattr(billing_plan_obj, limit_key, None)
                    if limit_value is not None:
                        limits_dict[limit_key] = limit_value

            # Build plan_limits list
            for limit_key, limit_value in limits_dict.items():
                if limit_key not in PLAN_LIMITS:
                    continue

                if limit_value is None or limit_value == -1:
                    limit_display = "Unlimited"
                else:
                    limit_display = str(limit_value)

                plan_limits.append(
                    {
                        "icon": PLAN_LIMITS[limit_key]["icon"],
                        "label": PLAN_LIMITS[limit_key]["label"],
                        "value": limit_display,
                    }
                )
        else:
            # Fallback: use billing_plan_limits if BillingPlan doesn't exist
            for limit_key, limit_value in billing_plan_limits.items():
                if limit_key not in PLAN_LIMITS:
                    continue
                plan_limits.append(
                    {
                        "icon": PLAN_LIMITS[limit_key]["icon"],
                        "label": PLAN_LIMITS[limit_key]["label"],
                        "value": "Unlimited" if limit_value == -1 or limit_value is None else str(limit_value),
                    }
                )

        return plan_limits
