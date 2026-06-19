"""Tests for billing API endpoints."""

import json

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.tests.fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    mock_stripe,
    sample_user,
)
from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.core.tests.shared_fixtures import team_with_business_plan  # noqa: F401
from sbomify.apps.sboms.models import SBOM, Component

# Import SBOM-related fixtures from sboms app
from sbomify.apps.sboms.tests.fixtures import sample_component, sample_sbom  # noqa: F401
from sbomify.apps.teams.models import Member, Team


@pytest.mark.django_db
def test_get_plans_unauthenticated(client: Client):
    """Test that unauthenticated users cannot access plans endpoint."""
    response = client.get(reverse("api-1:get_plans"))
    assert response.status_code == 401


@pytest.mark.django_db
def test_get_plans(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811
    enterprise_plan: BillingPlan,  # noqa: F811
):
    """Test retrieving all available billing plans."""
    client.force_login(sample_user)
    response = client.get(reverse("api-1:get_plans"))

    assert response.status_code == 200
    data = json.loads(response.content)

    assert len(data) == 3
    plan_keys = {plan["key"] for plan in data}
    assert plan_keys == {"community", "business", "enterprise"}


@pytest.mark.django_db
def test_get_usage_no_team(client: Client, sample_user: AbstractBaseUser):  # noqa: F811
    """Test usage endpoint without team selection."""
    client.force_login(sample_user)

    # Ensure session is empty
    session = client.session
    session["current_team"] = {}
    session.save()

    response = client.get(reverse("api-1:get_usage"))

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "detail" in data
    assert data["detail"] == "No team selected"


@pytest.mark.django_db
def test_get_usage(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
):
    """Test retrieving team's usage statistics."""
    from sbomify.apps.sboms.models import Component, ProductComponent

    client.force_login(sample_user)

    product = team_with_business_plan.product_set.create(name="Test Product")
    component = Component.objects.create(name="Test Component", team=team_with_business_plan)
    ProductComponent.objects.create(product=product, component=component)

    response = client.get(f"{reverse('api-1:get_usage')}?team_key={team_with_business_plan.key}")

    assert response.status_code == 200
    data = json.loads(response.content)

    assert data["products"] == 1
    assert data["components"] == 1


@pytest.mark.django_db
def test_get_usage_token_scope_gate(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
):
    """get_usage is a READ_MEMBER action gated by can("workspace:read", team).

    A publish-only token must be rejected (403); a read_only token and a full
    (unscoped) token must both pass (200). sample_user is already an owner member
    of the team via the fixture, so only the token scope distinguishes the cases.
    """

    def tok(scopes: list[str] | None) -> str:
        token_str = create_personal_access_token(sample_user)
        AccessToken.objects.create(
            user=sample_user,
            encoded_token=token_str,
            team=team_with_business_plan,
            scopes=scopes,
            description="scope-gate test token",
        )
        return token_str

    url = f"{reverse('api-1:get_usage')}?team_key={team_with_business_plan.key}"

    pub = tok(["artifact:publish"])
    response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {pub}")
    assert response.status_code == 403, response.content

    ro = tok(SCOPE_PRESETS["read_only"])
    response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {ro}")
    assert response.status_code == 200, response.content

    full = tok(None)
    response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {full}")
    assert response.status_code == 200, response.content


@pytest.mark.django_db
def test_change_plan_unauthorized_user(
    client: Client,
    guest_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811
):
    """Test that non-team-owners cannot change plans."""
    # Add guest user as a regular member (not owner) of the team
    Member.objects.create(
        user=guest_user,
        team=team_with_business_plan,
        role="member",  # Make sure this matches the role choices in settings
    )

    client.force_login(guest_user)

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": community_plan.key, "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 403
    data = json.loads(response.content)
    assert "Only workspace owners can change billing plans" in data["detail"]


@pytest.mark.django_db
def test_change_plan_to_community(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811,
):
    """Test downgrading to community plan."""
    client.force_login(sample_user)

    # Update team key to one that won't have a Stripe customer
    team_with_business_plan.key = "no-stripe-customer"
    team_with_business_plan.save()

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": community_plan.key, "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert "redirect_url" in data

    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan == community_plan.key
    assert "max_products" in team_with_business_plan.billing_plan_limits
    assert "max_components" in team_with_business_plan.billing_plan_limits


@pytest.mark.django_db
def test_change_plan_no_team_selected(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811
):
    """Test changing plan without selecting a team."""
    client.force_login(sample_user)

    # Explicitly clear the session data
    session = client.session
    session["current_team"] = {}
    session.save()

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"plan": community_plan.key, "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 404
    data = json.loads(response.content)
    assert "No team selected" in data["detail"]


@pytest.mark.django_db
def test_change_plan_invalid_plan(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
):
    """Test changing to a non-existent plan."""
    client.force_login(sample_user)

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": "non_existent_plan", "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 400
    data = json.loads(response.content)
    assert "Invalid plan" in data["detail"]


@pytest.mark.django_db
def test_change_plan_to_business_monthly(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811
):
    """Test changing to business plan with monthly billing."""
    client.force_login(sample_user)
    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": "business", "billing_period": "monthly"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert "redirect_url" in data


@pytest.mark.django_db
def test_change_plan_to_business_annual(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811
):
    """Test changing to business plan with annual billing."""
    client.force_login(sample_user)
    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": "business", "billing_period": "annual"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert "redirect_url" in data


@pytest.mark.django_db
def test_change_plan_business_upgrade_passes_allow_promotion_codes(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    """Business upgrade via change-plan API creates a Stripe session with promo codes enabled.

    Regression guard: a previous version of `stripe_client.create_checkout_session`
    omitted `allow_promotion_codes` from the session_data, so promo codes typed
    into Stripe's hosted checkout were silently ignored on this code path.
    """
    import stripe

    captured_kwargs: dict = {}

    class TrackingCheckoutSession:
        def __init__(self) -> None:
            self.url = "https://checkout.stripe.com/test"

        @classmethod
        def create(cls, **kwargs):
            captured_kwargs.update(kwargs)
            return cls()

    # Override the autouse mock_stripe fixture's CheckoutSession.create with one
    # that captures kwargs so we can assert on them.
    monkeypatch.setattr(stripe.checkout.Session, "create", TrackingCheckoutSession.create)

    client.force_login(sample_user)
    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": "business", "billing_period": "monthly"}),
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    assert captured_kwargs.get("allow_promotion_codes") is True, (
        "change-plan API must enable Stripe's promotion-code field on the hosted checkout page"
    )


@pytest.mark.django_db
def test_change_plan_to_community_with_active_subscription(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811,
):
    """Test downgrading to community plan with an active subscription."""
    client.force_login(sample_user)

    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": community_plan.key, "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert "redirect_url" in data

    # Verify team was updated
    team_with_business_plan.refresh_from_db()
    assert team_with_business_plan.billing_plan == community_plan.key


@pytest.mark.django_db
def test_changing_to_community_makes_sboms_public(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    community_plan: BillingPlan,  # noqa: F811
):
    """Test that changing to community plan makes all team's SBOMs public."""
    # Create 3 private components with their SBOMs
    components = [
        Component.objects.create(
            name=f"Private Component {i}",
            team=team_with_business_plan,
            visibility=Component.Visibility.PRIVATE,
        )
        for i in range(3)
    ]

    for component in components:
        SBOM.objects.create(name=f"SBOM for {component.name}", version="1.0.0", component=component)

    client.force_login(sample_user)
    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team_with_business_plan.key, "plan": community_plan.key, "billing_period": None}),
        content_type="application/json",
    )

    assert response.status_code == 200
    # Verify all components (and their SBOMs) are now public
    for component in Component.objects.filter(team=team_with_business_plan):
        assert component.visibility == Component.Visibility.PUBLIC


@pytest.mark.django_db
def test_changing_to_business_keeps_sboms_private(
    client: Client,
    sample_user: AbstractBaseUser,  # noqa: F811
    sample_component: Component,  # noqa: F811
    sample_sbom: SBOM,  # noqa: F811
    business_plan: BillingPlan,  # noqa: F811
    enterprise_plan: BillingPlan,  # noqa: F811
):
    """Test changing from enterprise to business plan maintains SBOM privacy."""
    team = sample_component.team
    team.billing_plan = enterprise_plan.key
    team.save()

    # Create private components with SBOMs under enterprise plan
    components = [
        Component.objects.create(name=f"Enterprise Component {i}", team=team, visibility=Component.Visibility.PRIVATE)
        for i in range(3)
    ]

    for component in components:
        SBOM.objects.create(name=f"SBOM for {component.name}", version="1.0.0", component=component)

    client.force_login(sample_user)
    response = client.post(
        reverse("api-1:change_plan"),
        json.dumps({"team_key": team.key, "plan": business_plan.key, "billing_period": "monthly"}),
        content_type="application/json",
    )

    assert response.status_code == 200

    # Verify components remain private
    for component in Component.objects.filter(team=team):
        assert component.visibility == Component.Visibility.PRIVATE

    # Verify SBOMs remain private through component relationship
    for sbom in SBOM.objects.filter(component__team=team):
        assert sbom.public_access_allowed is False
