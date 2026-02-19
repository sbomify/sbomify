from typing import TypedDict

from ninja import Schema
from pydantic import Field


class BillingLimitsData(TypedDict, total=False):
    """Type definition for Team.billing_plan_limits JSON field."""

    max_products: int | None
    max_projects: int | None
    max_components: int | None
    stripe_customer_id: str
    stripe_subscription_id: str
    billing_period: str
    subscription_status: str
    is_trial: bool
    trial_end: int | None
    cancel_at_period_end: bool
    scheduled_downgrade_plan: str | None
    next_billing_date: str | None
    last_updated: str
    last_processed_webhook_id: str | None


class PlanSchema(Schema):
    key: str
    name: str
    description: str
    max_products: int | None
    max_projects: int | None
    max_components: int | None


class UsageSchema(Schema):
    products: int
    projects: int
    components: int
    current_plan: str | None


class ChangePlanRequest(Schema):
    plan: str = Field(..., max_length=30, pattern=r"^[a-z_]+$")
    billing_period: str | None = Field(None, max_length=10, pattern=r"^(monthly|annual)$")
    team_key: str | None = Field(None, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")


class ChangePlanResponse(Schema):
    redirect_url: str | None = None
