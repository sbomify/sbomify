from ninja import Schema


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
    plan: str
    billing_period: str | None = None
    team_key: str | None = None
    promo_code: str | None = None


class ChangePlanResponse(Schema):
    redirect_url: str | None = None
