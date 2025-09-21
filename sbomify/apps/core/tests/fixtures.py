import os
from typing import Any, Generator

import pytest
from django.contrib.auth.base_user import AbstractBaseUser

from sbomify.apps.billing.models import BillingPlan


@pytest.fixture
def sample_user(
    django_user_model: type[AbstractBaseUser],
) -> Generator[AbstractBaseUser, Any, None]:
    """Create a sample user."""
    user = django_user_model(
        username=os.environ["DJANGO_TEST_USER"],
        email=os.environ["DJANGO_TEST_EMAIL"],
        first_name="Test",
        last_name="User",
    )
    user.set_password(os.environ["DJANGO_TEST_PASSWORD"])
    user.save()

    yield user

    user.delete()


@pytest.fixture
def guest_user(django_user_model: type[AbstractBaseUser]) -> Generator[AbstractBaseUser, Any, None]:
    """Create a sample user."""
    user = django_user_model(
        username="guest",
        email="guest@example.com",
        first_name="Guest",
        last_name="User",
    )
    user.set_password("guest")
    user.save()

    yield user

    user.delete()


@pytest.fixture
def ensure_billing_plans(db) -> None:
    """Ensure billing plans exist for tests."""
    # Create the billing plans that are expected by the signal handlers
    BillingPlan.objects.get_or_create(
        key="business",
        defaults={
            "name": "Business",
            "description": "Pro plan for medium teams",
            "max_products": 5,
            "max_projects": 10,
            "max_components": 200,
            "max_users": 10,
            "stripe_product_id": "prod_test_business",
            "stripe_price_monthly_id": "price_test_business_monthly",
            "stripe_price_annual_id": "price_test_business_annual",
        },
    )
    BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Community plan for small teams",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "max_users": 2,
        },
    )
    BillingPlan.objects.get_or_create(
        key="enterprise",
        defaults={
            "name": "Enterprise",
            "description": "Enterprise plan for large teams",
            "max_products": None,
            "max_projects": None,
            "max_components": None,
            "max_users": None,
            "stripe_product_id": "prod_test_enterprise",
            "stripe_price_monthly_id": "price_test_enterprise_monthly",
            "stripe_price_annual_id": "price_test_enterprise_annual",
        },
    )
