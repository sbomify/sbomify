from ninja import Schema
from pydantic import Field


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
    billing_period: str | None = Field(None, pattern=r"^(monthly|annual)$")
    team_key: str | None = Field(None, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")


class ChangePlanResponse(Schema):
    redirect_url: str | None = None
