import stripe
from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse
from ninja import Router
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.schemas import ErrorResponse
from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.teams.models import Team

from .models import BillingPlan
from .schemas import ChangePlanRequest, ChangePlanResponse, PlanSchema, UsageSchema

router = Router(tags=["Billing"], auth=(PersonalAccessTokenAuth(), django_auth))


@router.get("/plans/", response={200: list[PlanSchema], 404: ErrorResponse})
def get_plans(request: HttpRequest):
    """Get all available billing plans."""
    plans = BillingPlan.objects.all()
    return 200, [
        PlanSchema.model_validate(
            {
                "key": plan.key,
                "name": plan.name,
                "description": plan.description,
                "max_products": plan.max_products,
                "max_projects": plan.max_projects,
                "max_components": plan.max_components,
            }
        )
        for plan in plans
    ]


@router.get("/usage/", response={200: UsageSchema, 404: ErrorResponse})
def get_usage(request: HttpRequest):
    """Get current team's usage statistics."""
    team_key = request.GET.get("team_key") or request.session.get("current_team", {}).get("key")
    if not team_key:
        return 404, {"detail": "No team selected"}

    try:
        team = Team.objects.get(key=team_key)

        # Count components directly associated with the team
        components_count = Component.objects.filter(team=team).count()

        return 200, UsageSchema(
            products=Product.objects.filter(team=team).count(),
            projects=Project.objects.filter(product__team=team).count(),
            components=components_count,
            current_plan=team.billing_plan if team.billing_plan else None,
        )
    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}


@router.post(
    "/change-plan/", response={200: ChangePlanResponse, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse}
)
def change_plan(request: HttpRequest, data: ChangePlanRequest):
    """Change the current team's billing plan."""

    team_key = data.team_key or request.session.get("current_team", {}).get("key")

    # print("team_key")
    # breakpoint()
    # print(team_key)

    if not team_key:
        return 404, {"detail": "No team selected"}

    try:
        team = Team.objects.get(key=team_key)

        # Check if user is team owner
        is_owner = team.members.filter(member__user=request.user, member__role="owner").exists()

        if not is_owner:
            return 403, {"detail": "Only team owners can change billing plans"}

        plan = BillingPlan.objects.get(key=data.plan)
        stripe.api_key = settings.STRIPE_SECRET_KEY
        customer_id = f"c_{team_key}"

        if plan.key == "community":
            try:
                customer = stripe.Customer.retrieve(customer_id)
                subscriptions = stripe.Subscription.list(customer=customer.id, limit=1)

                if subscriptions.data:
                    # Cancel at period end
                    stripe.Subscription.modify(subscriptions.data[0].id, cancel_at_period_end=True)
                    team.billing_plan = plan.key
                    team.billing_plan_limits = {
                        "max_products": plan.max_products,
                        "max_projects": plan.max_projects,
                        "max_components": plan.max_components,
                        "stripe_subscription_id": subscriptions.data[0].id,
                        "subscription_status": "canceled",
                    }

                    # Update both components and SBOMs
                    Component.objects.filter(team=team).update(is_public=True)

                else:
                    team.billing_plan = plan.key
                    team.billing_plan_limits = {
                        "max_products": plan.max_products,
                        "max_projects": plan.max_projects,
                        "max_components": plan.max_components,
                    }
                    # Update components even without subscription
                    Component.objects.filter(team=team).update(is_public=True)

            except stripe.error.InvalidRequestError:
                team.billing_plan = plan.key
                team.billing_plan_limits = {
                    "max_products": plan.max_products,
                    "max_projects": plan.max_projects,
                    "max_components": plan.max_components,
                }
                # Update components for non-Stripe customers
                Component.objects.filter(team=team).update(is_public=True)

            team.save()
            return 200, {"success": True}

        elif plan.key == "business":
            # Create Stripe checkout session
            try:
                customer = stripe.Customer.retrieve(customer_id)
            except stripe.error.InvalidRequestError:
                customer = stripe.Customer.create(
                    id=customer_id,
                    email=request.user.email,
                    name=team.name,
                    metadata={"team_key": team_key},
                )

            # Get the price ID based on billing period
            price_id = plan.stripe_price_annual_id if data.billing_period == "annual" else plan.stripe_price_monthly_id

            success_url = (
                request.build_absolute_uri(reverse("billing:billing_return")) + "?session_id={CHECKOUT_SESSION_ID}"
            )

            session_data = {
                "customer": customer.id,
                "success_url": success_url,
                "cancel_url": request.build_absolute_uri("/"),
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "metadata": {"team_key": team_key},
            }

            # Add promo code if provided
            if data.promo_code:
                session_data["discounts"] = [{"coupon": data.promo_code}]

            session = stripe.checkout.Session.create(**session_data)

            return 200, ChangePlanResponse(redirect_url=session.url)

        return 400, {"detail": "Invalid plan"}

    except Team.DoesNotExist:
        return 404, {"detail": "Team not found"}
    except BillingPlan.DoesNotExist:
        return 400, {"detail": "Invalid plan"}
    except Exception:
        return 400, {"detail": "Invalid request"}
