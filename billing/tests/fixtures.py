from typing import Any
import json

import pytest
import stripe
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from billing.models import BillingPlan
from core.tests.fixtures import sample_user  # noqa: F401
from sboms.models import Component, Product, ProductProject, Project, ProjectComponent
from teams.models import Member, Team


@pytest.fixture
def community_plan() -> BillingPlan:
    """Free community plan fixture."""
    return BillingPlan.objects.create(
        key="community",
        name="Community",
        description="Free plan for small teams",
        max_products=1,
        max_projects=1,
        max_components=5,
        stripe_product_id=None,
        stripe_price_monthly_id=None,
        stripe_price_annual_id=None,
    )


@pytest.fixture
def business_plan() -> BillingPlan:
    """Business plan fixture."""
    return BillingPlan.objects.create(
        key="business",
        name="Business",
        description="For growing teams",
        max_products=10,
        max_projects=20,
        max_components=100,
        stripe_product_id="prod_test_business",
        stripe_price_monthly_id="price_test_business_monthly",  # $199/month
        stripe_price_annual_id="price_test_business_annual",  # $159 * 12/year
    )


@pytest.fixture
def enterprise_plan() -> BillingPlan:
    """Enterprise plan fixture with unlimited resources."""
    return BillingPlan.objects.create(
        key="enterprise",
        name="Enterprise",
        description="For large organizations",
        max_products=None,
        max_projects=None,
        max_components=None,
        stripe_product_id="prod_test_enterprise",
        stripe_price_monthly_id="price_test_enterprise_monthly",
        stripe_price_annual_id="price_test_enterprise_annual",
    )


@pytest.fixture
def team_with_business_plan(sample_user: AbstractBaseUser, business_plan: BillingPlan) -> Team:  # noqa: F811
    """Team fixture with active business plan subscription."""
    team = Team.objects.create(
        name="Test Business Team",
        key="test_business_team",
        billing_plan=business_plan.key,
        billing_plan_limits={
            "max_products": business_plan.max_products,
            "max_projects": business_plan.max_projects,
            "max_components": business_plan.max_components,
            "stripe_customer_id": "c_test_business_team",
            "stripe_subscription_id": "sub_test123",
            "subscription_status": "active",
        },
    )
    Member.objects.create(team=team, user=sample_user, role="owner")
    return team


@pytest.fixture(autouse=True)
def mock_stripe(monkeypatch):
    """Mock all Stripe functionality for tests.

    This fixture automatically mocks all Stripe operations including:
    - API key configuration
    - Customer operations (create, retrieve)
    - Subscription operations (list, modify)
    - Checkout Session operations (create)
    - Webhook signature verification
    - Webhook secret

    No real Stripe API calls will be made when this fixture is active.
    """
    # Mock the API key and webhook secret
    monkeypatch.setattr(stripe, "api_key", "sk_test_dummy_key_for_ci")
    monkeypatch.setattr("django.conf.settings.STRIPE_WEBHOOK_SECRET", "whsec_test_webhook_secret_key")

    # Mock Customer operations
    class MockCustomer:
        @classmethod
        def retrieve(cls, id, **kwargs):
            if id == "c_no-stripe-customer":
                raise stripe.error.InvalidRequestError("Customer not found", param="customer")
            instance = cls()
            instance.id = id
            return instance

        @classmethod
        def create(cls, **kwargs):
            instance = cls()
            instance.id = kwargs.get('id')
            instance.email = kwargs.get('email')
            instance.name = kwargs.get('name')
            instance.metadata = kwargs.get('metadata', {})
            return instance

    # Mock Subscription operations
    class MockSubscription:
        @classmethod
        def list(cls, customer, limit=1):
            class SubscriptionList:
                data = []
            return SubscriptionList()

        @classmethod
        def modify(cls, subscription_id, **kwargs):
            pass

    # Mock Checkout Session operations
    class MockCheckoutSession:
        def __init__(self):
            self.url = "https://checkout.stripe.com/test"

        @classmethod
        def create(cls, **kwargs):
            instance = cls()
            return instance

    # Mock Webhook operations
    class MockWebhook:
        @classmethod
        def construct_event(cls, payload, sig_header, secret):
            """Mock Stripe webhook event construction.

            Args:
                payload: The webhook payload as a string
                sig_header: The signature header
                secret: The webhook secret

            Returns:
                The constructed event object
            """
            if sig_header == "invalid_signature":
                raise stripe.error.SignatureVerificationError("Invalid", "sig")

            # Parse the payload
            data = json.loads(payload)

            # Convert dictionary to object with attributes recursively
            def dict_to_obj(d):
                if isinstance(d, dict):
                    # Create a new object that allows attribute access
                    obj = type('StripeObject', (), {})()
                    for key, value in d.items():
                        setattr(obj, key, dict_to_obj(value))
                    return obj
                elif isinstance(d, list):
                    return [dict_to_obj(item) for item in d]
                else:
                    return d

            # Create a mock event object with proper attribute access
            class StripeEvent:
                def __init__(self, event_type, data_object):
                    self.type = event_type
                    self.data = type('EventData', (), {'object': dict_to_obj(data_object)})()

            # For checkout.session.completed events, return the session object directly
            if data.get("type") == "checkout.session.completed":
                return StripeEvent("checkout.session.completed", data["data"]["object"])

            # For other events, wrap the data in a proper event object
            return StripeEvent(data["type"], data["data"]["object"])

    # Apply all mocks
    monkeypatch.setattr(stripe.Customer, "retrieve", MockCustomer.retrieve)
    monkeypatch.setattr(stripe.Customer, "create", MockCustomer.create)
    monkeypatch.setattr(stripe.Subscription, "list", MockSubscription.list)
    monkeypatch.setattr(stripe.Subscription, "modify", MockSubscription.modify)
    monkeypatch.setattr(stripe.checkout.Session, "create", MockCheckoutSession.create)
    monkeypatch.setattr(stripe.Webhook, "construct_event", MockWebhook.construct_event)

    return "sk_test_dummy_key_for_ci"


@pytest.fixture
def test_product(team_with_business_plan: Team) -> Product:
    """Create a test product and clean it up after the test."""
    product = Product.objects.create(name="Test Product", team=team_with_business_plan)
    yield product
    product.delete()


@pytest.fixture
def multiple_products(team_with_business_plan: Team, community_plan: BillingPlan) -> list[Product]:
    """Create multiple products exceeding community plan limits and clean up after test."""
    products = []
    for i in range(community_plan.max_products + 1):
        products.append(Product.objects.create(name=f"Test Product {i}", team=team_with_business_plan))
    yield products
    for product in products:
        product.delete()


@pytest.fixture
def test_project(team_with_business_plan: Team) -> Project:
    """Create a test project and clean it up after the test."""
    project = Project.objects.create(
        name=f"Test Project {team_with_business_plan.key}",
        team=team_with_business_plan,
    )
    yield project
    project.delete()


@pytest.fixture
def multiple_projects(
    team_with_business_plan: Team, test_product: Product, community_plan: BillingPlan
) -> list[Project]:
    """Create multiple projects exceeding community plan limits and clean up after test."""
    projects = []
    for i in range(community_plan.max_projects + 1):
        project = Project.objects.create(
            name=f"Test Project {team_with_business_plan.key} {i}",
            team=team_with_business_plan,
        )
        ProductProject.objects.create(
            product=test_product,
            project=project,
        )
        projects.append(project)
    yield projects
    for project in projects:
        project.delete()


@pytest.fixture
def multiple_components(
    team_with_business_plan: Team, test_project: Project, community_plan: BillingPlan
) -> list[Component]:
    """Create multiple components exceeding community plan limits and clean up after test."""
    components = []
    for i in range(community_plan.max_components + 1):
        component = Component.objects.create(name=f"Test Component {i}", team=team_with_business_plan)
        ProjectComponent.objects.create(
            project=test_project,
            component=component,
        )
        components.append(component)
    yield components
    for component in components:
        component.delete()
