import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.apis import _check_billing_limits
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.schemas import ErrorCode
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


@pytest.mark.django_db
def test_scheduled_downgrade_checks_the_target_plan_limit(mocker):
    """A workspace that cancelled a paid plan cannot outgrow the plan it drops to."""
    mocker.patch("sbomify.apps.core.apis.get_subscription_cancel_at_period_end", return_value=True)
    BillingPlan.objects.create(key="community", name="Community", max_products=1, max_components=1)
    BillingPlan.objects.create(key="business", name="Business", max_products=5, max_components=5)
    team = Team.objects.create(
        name="Downgrading Team",
        billing_plan="business",
        billing_plan_limits={
            "cancel_at_period_end": True,
            "scheduled_downgrade_plan": "community",
            "stripe_subscription_id": "sub_test",
            "stripe_customer_id": "cus_test",
        },
    )
    Product.objects.create(name="P1", team=team)

    can_create, msg, code = _check_billing_limits(str(team.id), "product")
    assert can_create is False
    assert "scheduled downgrade to Community" in msg
    assert code == ErrorCode.BILLING_LIMIT_EXCEEDED

    # Under the target plan's limit, the current plan decides.
    assert _check_billing_limits(str(team.id), "component") == (True, "", None)

    # An unsupported type passes the downgrade check, then is refused as invalid.
    can_create, _, code = _check_billing_limits(str(team.id), "release")
    assert can_create is False
    assert code == ErrorCode.INVALID_DATA
