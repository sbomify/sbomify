import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.apis import _check_billing_limits
from sbomify.apps.core.models import Component, Product
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
def test_resource_limits_default_plan():
    """Test resource limits for teams with no explicit billing plan (default)."""

    BillingPlan.objects.create(
        key="community",
        name="Community Plan",
        description="Community Plan",
        max_products=1,
        max_components=1,
    )

    team = Team.objects.create(name="Default Team", billing_plan=None)

    can_create, _, _ = _check_billing_limits(str(team.id), "product")
    assert can_create is True

    Product.objects.create(name="P1", team=team)

    can_create, msg, _ = _check_billing_limits(str(team.id), "product")
    assert can_create is False
    assert "maximum 1 products" in msg

    can_create, _, _ = _check_billing_limits(str(team.id), "component")
    assert can_create is True

    Component.objects.create(name="Comp1", team=team, component_type="application")

    can_create, msg, _ = _check_billing_limits(str(team.id), "component")
    assert can_create is False
    assert "maximum 1 components" in msg
