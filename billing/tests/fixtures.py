from typing import Any

import pytest
import stripe
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from billing.models import BillingPlan
from core.fixtures import guest_user, sample_user  # noqa: F401
from sboms.models import SBOM, Component, Product, ProductProject, Project, ProjectComponent
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
        max_products=5,
        max_projects=50,  # 10 projects per product * 5 products
        max_components=10000,  # 200 components per project * 50 projects
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


class MockStripeSession:
    def __init__(
        self,
        id: str,
        object: str,
        client_reference_id: str,
        customer: str,
        subscription: str,
        payment_status: str,
        status: str,
        created: int,
        url: str,
        type: str,
    ):
        self.id = id
        self.object = object
        self.client_reference_id = client_reference_id
        self.customer = customer
        self.subscription = subscription
        self.payment_status = payment_status
        self.status = status
        self.created = created
        self.url = url
        self.type = type

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "object": self.object,
            "client_reference_id": self.client_reference_id,
            "customer": self.customer,
            "subscription": self.subscription,
            "payment_status": self.payment_status,
            "status": self.status,
            "created": self.created,
            "url": self.url,
            "type": self.type,
        }


@pytest.fixture
def mock_stripe_session() -> MockStripeSession:
    """Mock Stripe checkout session data."""

    return MockStripeSession(
        id="cs_test_123",
        object="checkout.session",
        client_reference_id="test-business-team",
        customer="cus_test123",
        subscription="sub_test123",
        payment_status="paid",
        status="complete",
        created=int(timezone.now().timestamp()),
        url="https://checkout.stripe.com/test-session",
        type="checkout.session.completed",
    )


@pytest.fixture
def mock_stripe_webhook_signature() -> str:
    """Mock Stripe webhook signature."""
    return "whsec_test123"


@pytest.fixture
def mock_stripe_checkout_session(monkeypatch):
    """Mock Stripe checkout session creation."""

    class MockSession:
        create_kwargs = {}  # Class variable to store create arguments

        def __init__(self):
            self.url = "https://checkout.stripe.com/test"

        @classmethod
        def create(cls, **kwargs):
            cls.create_kwargs = kwargs  # Store the kwargs at class level
            instance = cls()
            return instance

        def get_create_kwargs(self):
            # Method to access the stored kwargs
            return self.__class__.create_kwargs

    monkeypatch.setattr(stripe.checkout.Session, "create", MockSession.create)
    return MockSession


@pytest.fixture
def mock_stripe_customer(monkeypatch):
    """Mock Stripe customer for testing."""
    class MockCustomer:
        @classmethod
        def retrieve(cls, id, **kwargs):
            if id.startswith("c_test"):
                instance = cls()
                instance.id = id
                return instance
            raise stripe.error.InvalidRequestError("Customer not found", param="customer")

    monkeypatch.setattr(stripe.Customer, "retrieve", MockCustomer.retrieve)
    return MockCustomer


@pytest.fixture
def mock_stripe_subscription(monkeypatch):
    """Mock Stripe subscription for testing."""
    class MockSubscription:
        @classmethod
        def list(cls, customer, limit=1):
            class SubscriptionList:
                data = []
            return SubscriptionList()

        @classmethod
        def modify(cls, subscription_id, **kwargs):
            pass

    monkeypatch.setattr(stripe.Subscription, "list", MockSubscription.list)
    monkeypatch.setattr(stripe.Subscription, "modify", MockSubscription.modify)
    return MockSubscription


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
