import pytest
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.models import Product, Project, Component
from sbomify.apps.core.apis import _check_billing_limits
from sbomify.apps.teams.models import Team

@pytest.mark.django_db
def test_resource_limits_default_plan():
    """Test resource limits for teams with no explicit billing plan (default)."""
    
    # 1. Setup community plan limits
    BillingPlan.objects.create(
        key="community",
        name="Community Plan",
        description="Community Plan",
        max_products=1,
        max_projects=1,
        max_components=1
    )
    
    # 2. Create team with NO billing plan
    team = Team.objects.create(name="Default Team", billing_plan=None)
    
    # 3. Test Product limits
    # Should be allowed (0 < 1)
    can_create, _, _ = _check_billing_limits(str(team.id), "product")
    assert can_create is True
    
    # Create 1 product
    Product.objects.create(name="P1", team=team)
    
    # Should be blocked (1 >= 1)
    can_create, msg, _ = _check_billing_limits(str(team.id), "product")
    assert can_create is False
    assert "maximum 1 products" in msg

    # 4. Test Project limits
    # Should be allowed (0 < 1)
    can_create, _, _ = _check_billing_limits(str(team.id), "project")
    assert can_create is True
    
    # Create 1 project
    Project.objects.create(name="Proj1", team=team)
    
    # Should be blocked (1 >= 1)
    can_create, msg, _ = _check_billing_limits(str(team.id), "project")
    assert can_create is False
    assert "maximum 1 projects" in msg

    # 5. Test Component limits
    # Should be allowed (0 < 1)
    can_create, _, _ = _check_billing_limits(str(team.id), "component")
    assert can_create is True
    
    # Create 1 component
    Component.objects.create(name="Comp1", team=team, component_type="application")
    
    # Should be blocked (1 >= 1)
    can_create, msg, _ = _check_billing_limits(str(team.id), "component")
    assert can_create is False
    assert "maximum 1 components" in msg
