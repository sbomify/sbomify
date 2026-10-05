"""
Service for calculating team pricing information for display.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Any, TypedDict

from django.db import DatabaseError, OperationalError, transaction

from sbomify.logging import getLogger

from .models import BillingPlan
from .stripe_client import StripeError, get_stripe_client
from .stripe_pricing_service import StripePricingService


class QuotaDisplay(TypedDict):
    """One quota tile: what the plan allows and what the workspace is using."""

    icon: str
    label: str
    value: str
    used: str
    unlimited: bool


logger = getLogger(__name__)


class TeamPricingService:
    """Service for calculating and formatting team pricing information."""

    def __init__(self) -> None:
        self.stripe_client = get_stripe_client()
        self.pricing_service = StripePricingService()

    def get_plan_pricing(
        self, team: Any, billing_plan_obj: BillingPlan | None = None, *, sync_from_stripe: bool = True
    ) -> dict[str, Any]:
        """
        Calculate pricing information for a team's billing plan.

        Args:
            team: Team instance
            billing_plan_obj: Optional BillingPlan instance. Its fields are never
                read: passing one only skips the existence lookup below, and with
                it the early return that lookup triggers when no plan row matches
                the team's billing_plan. So it changes whether this method runs
                at all, not what it computes.
            sync_from_stripe: Whether to refresh the subscription from Stripe before
                pricing it. Pass False when the caller has already synced, or has
                decided not to. Note this suppresses only the subscription sync:
                this method can still reach Stripe to list a customer's
                subscriptions when none is stored, and to fetch an invoice amount
                when the cached fields are missing. A caller that must not touch
                Stripe at all should not call this method.

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
        plan_pricing: dict[str, Any] = {"amount": "Contact us", "period": "", "billing_period": None}

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
        next_billing_date: Any = billing_plan_limits.get("next_billing_date")

        from .config import is_billing_enabled

        # Attempt to recover missing subscription ID if we have a customer ID
        has_customer = not stripe_subscription_id and stripe_customer_id
        if is_billing_enabled() and has_customer and billing_plan in ["business", "enterprise"]:
            try:
                # List active subscriptions for the customer
                subscriptions = self.stripe_client.list_subscriptions(str(stripe_customer_id), limit=1)
                if subscriptions and subscriptions.data:
                    stripe_subscription_id = subscriptions.data[0].id
                    # We will save this implicitly when we fetch invoice amount below if we update the limits
                    # But better to save it now or let the fetch mechanism handle it?
                    # valid_billing_relationship constraint requires both to be set.
                    # Let's rely on _fetch_invoice_amount to update the limits if we pass the ID.
            except StripeError as e:
                logger.error(f"Failed to recover subscription ID for team: {e}")
            except Exception as e:
                logger.error(f"Unexpected error recovering subscription ID for team: {e}")

        # Community plan is always free
        if billing_plan == "community":
            return {"amount": "$0", "period": "forever", "billing_period": None}

        # Sync subscription data from Stripe first to ensure we have latest status
        # Note: team might be a Pydantic schema, so we need to get the actual model instance
        #
        # ``sync_from_stripe=False`` is for a caller that has already synced, or
        # has decided not to. The settings view is both: it renders eight tabs
        # from this service and only one of them displays what Stripe would say,
        # so syncing here as well meant every tab paid for the call twice.
        if sync_from_stripe and is_billing_enabled() and stripe_subscription_id:
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
                billing_period = billing_plan_limits.get("billing_period")

                # Also update team's billing_plan_limits if it's a schema
                if hasattr(team, "key") and not hasattr(team, "pk"):
                    # Update the schema object with synced data
                    team.billing_plan_limits = billing_plan_limits

            except Exception as e:
                logger.warning(f"Failed to sync subscription for pricing display: {e}")

        # Try to fetch invoice and date if we don't have them
        needs_invoice = last_payment_amount is None or next_billing_date is None
        if is_billing_enabled() and needs_invoice and stripe_subscription_id:
            last_payment_amount, last_payment_currency, next_billing_date = self._fetch_invoice_amount(
                stripe_subscription_id, team
            )

        # Ensure next_billing_date is a datetime object for template formatting
        if next_billing_date:
            if isinstance(next_billing_date, str):
                try:
                    # Try parsing ISO format string
                    next_billing_date = datetime.fromisoformat(next_billing_date.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    try:
                        # Try parsing as timestamp
                        next_billing_date = datetime.fromtimestamp(float(next_billing_date), tz=dt_timezone.utc)
                    except (ValueError, TypeError):
                        logger.warning("Failed to parse next_billing_date")
                        next_billing_date = None
            elif isinstance(next_billing_date, (int, float)):
                # Handle timestamp
                try:
                    next_billing_date = datetime.fromtimestamp(next_billing_date, tz=dt_timezone.utc)
                except (ValueError, OSError):
                    logger.warning("Failed to convert timestamp to datetime")
                    next_billing_date = None
            # Ensure timezone-aware
            if next_billing_date and isinstance(next_billing_date, datetime) and next_billing_date.tzinfo is None:
                from django.utils import timezone as django_timezone

                next_billing_date = django_timezone.make_aware(next_billing_date)

        # Use actual paid amount if available
        if last_payment_amount is not None:
            currency_symbol = "$" if last_payment_currency == "usd" else str(last_payment_currency).upper() + " "
            period_display = "per month" if billing_period == "monthly" else "per year"

            return {
                "amount": f"{currency_symbol}{last_payment_amount:,.0f}",
                "period": period_display,
                "billing_period": billing_period,
                "next_billing_date": next_billing_date,
            }

        # Fall back to plan pricing from Stripe
        if is_billing_enabled() and billing_plan in ["business", "enterprise"]:
            pricing = self._get_plan_pricing_from_stripe(billing_plan, billing_period)
            if next_billing_date:
                pricing["next_billing_date"] = next_billing_date
            return pricing

        return plan_pricing

    def _fetch_invoice_amount(self, subscription_id: str, team: Any) -> tuple[float | None, str, str | None]:
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
            amount: float | None = None
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
                logger.warning(f"Failed to fetch invoice details: {e}")

            # Cache what we found
            from sbomify.apps.teams.models import Team

            # Get actual Team model instance if team is a schema
            if hasattr(team, "key") and not hasattr(team, "pk"):
                # It's a Pydantic schema, fetch the model instance
                team_obj = Team.objects.get(key=team.key)
            else:
                # It's already a model instance
                team_obj = team

            try:
                with transaction.atomic():
                    locked_team = Team.objects.select_for_update().get(pk=team_obj.pk)
                    billing_plan_limits = locked_team.billing_plan_limits or {}

                    if amount is not None:
                        billing_plan_limits["last_payment_amount"] = amount
                        billing_plan_limits["last_payment_currency"] = currency

                    if next_billing_date:
                        billing_plan_limits["next_billing_date"] = next_billing_date

                    billing_plan_limits["stripe_subscription_id"] = subscription_id

                    cancel_at_period_end = getattr(subscription, "cancel_at_period_end", False)
                    billing_plan_limits["cancel_at_period_end"] = cancel_at_period_end

                    locked_team.billing_plan_limits = billing_plan_limits
                    locked_team.save(update_fields=["billing_plan_limits"])
            except (DatabaseError, OperationalError) as db_error:
                # Non-critical read path — stale cached data is acceptable.
                # No retry: callers fall back to existing billing_plan_limits.
                logger.error(f"Failed to update limits on render path: {db_error}")
            except Exception as e:
                logger.error(f"Unexpected error updating limits: {e}")

            return amount, currency, next_billing_date

        except StripeError as e:
            logger.error(f"Failed to fetch subscription for team: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching subscription for team: {e}")

        return None, "usd", None

    def _get_plan_pricing_from_stripe(self, billing_plan: str, billing_period: Any) -> dict[str, Any]:
        """Get pricing from Stripe pricing service."""
        try:
            stripe_pricing = self.pricing_service.get_all_plans_pricing(force_refresh=False)
            plan_stripe_data = stripe_pricing.get(billing_plan, {})

            monthly_discounted = plan_stripe_data.get("monthly_price_discounted")
            annual_discounted = plan_stripe_data.get("annual_price_discounted")

            if billing_period == "annual" and annual_discounted:
                return {
                    "amount": f"${float(annual_discounted):,.0f}",
                    "period": "per year",
                    "billing_period": "annual",
                }
            elif billing_period == "monthly" and monthly_discounted:
                return {
                    "amount": f"${float(monthly_discounted):,.0f}",
                    "period": "per month",
                    "billing_period": "monthly",
                }
            elif monthly_discounted:
                # Default to monthly if billing_period is not set
                return {
                    "amount": f"${float(monthly_discounted):,.0f}",
                    "period": "per month",
                    "billing_period": None,
                }
            elif annual_discounted:
                return {
                    "amount": f"${float(annual_discounted):,.0f}",
                    "period": "per year",
                    "billing_period": None,
                }
        except Exception as e:
            logger.error(f"Failed to get pricing from Stripe: {e}")

        return {"amount": "Custom", "period": "pricing", "billing_period": None}

    def get_plan_limits(self, team: Any, billing_plan_obj: BillingPlan | None = None) -> list[QuotaDisplay]:
        """Each quota the plan enforces, with what the workspace is using against it.

        A bare limit does not answer the question anyone opens this page with,
        which is how close they are to it. Members is here because it is an
        enforced quota: leaving it out hid the one limit that blocks an invite.
        """
        PLAN_LIMITS: dict[str, dict[str, str]] = {
            "max_users": {
                "label": "Members",
                "icon": "users",
                "usage": "members",
            },
            "max_products": {
                "label": "Products",
                "icon": "cube",
                "usage": "products",
            },
            "max_components": {
                "label": "Components",
                "icon": "puzzle-piece",
                "usage": "components",
            },
        }

        usage = self.get_workspace_usage(team)
        billing_plan_limits = team.billing_plan_limits or {}

        if billing_plan_obj is None:
            billing_plan = team.billing_plan or "community"
            try:
                billing_plan_obj = BillingPlan.objects.get(key=billing_plan)
            except BillingPlan.DoesNotExist:
                billing_plan_obj = None

        # An unlimited quota is stored as None on the model and as -1 in the
        # cached limits. Both are a value to show, so the key is always kept:
        # dropping it left the tile out and the row half empty.
        limits_dict: dict[str, Any] = {}
        for limit_key in PLAN_LIMITS:
            if limit_key in billing_plan_limits:
                limits_dict[limit_key] = billing_plan_limits[limit_key]
            elif billing_plan_obj is not None:
                limits_dict[limit_key] = getattr(billing_plan_obj, limit_key, None)

        plan_limits: list[QuotaDisplay] = []
        for limit_key, limit_value in limits_dict.items():
            unlimited = limit_value is None or limit_value == -1
            label = PLAN_LIMITS[limit_key]["label"]
            if limit_key == "max_users" and usage["pending_invites"]:
                # Pending invitations hold a seat, so the quota counts them. A
                # tile reading "Members" alone would disagree with the number
                # above it and with the guard that blocks the next invite.
                label = "Members and invitations"
            plan_limits.append(
                QuotaDisplay(
                    icon=PLAN_LIMITS[limit_key]["icon"],
                    label=label,
                    value="Unlimited" if unlimited else str(limit_value),
                    used=str(usage[PLAN_LIMITS[limit_key]["usage"]]),
                    unlimited=unlimited,
                )
            )

        return plan_limits

    def get_workspace_usage(self, team: Any) -> dict[str, int]:
        """What the workspace is currently using, keyed like the quotas.

        Seats come from the query the seat check itself uses: human members with
        bots excluded, plus the invitations already holding a place. A plain
        member count would read under on a workspace with invitations out and
        over on one with OIDC publishers.
        """
        from sbomify.apps.core.models import Component, Product
        from sbomify.apps.teams.queries import get_team_user_counts

        _, pending_invites, seats = get_team_user_counts(team.id)
        return {
            "members": seats,
            "pending_invites": pending_invites,
            "products": Product.objects.filter(team=team).count(),
            "components": Component.objects.filter(team=team).count(),
        }
