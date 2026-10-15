"""Generic billing functionality tests."""
import pytest

from sbomify.apps.billing.models import BillingPlan

from .fixtures import (  # noqa: F401
    business_plan,
    multiple_components,
    multiple_products,
    sample_user,
    test_product,
)


@pytest.mark.django_db
def test_billing_plan_str_representation(business_plan: BillingPlan):
    """Test string representation of BillingPlan model."""
    assert str(business_plan) == "Business (business)"

