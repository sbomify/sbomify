"""Generic billing functionality tests."""
import pytest

from sbomify.apps.billing.models import BillingPlan

from .fixtures import business_plan  # noqa: F401


@pytest.mark.django_db
def test_billing_plan_str_representation(business_plan: BillingPlan):
    """Test string representation of BillingPlan model."""
    assert str(business_plan) == "Business (business)"
