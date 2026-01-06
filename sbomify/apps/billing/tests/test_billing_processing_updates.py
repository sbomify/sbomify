import pytest
from unittest.mock import MagicMock
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.billing_processing import handle_subscription_updated
from sbomify.apps.teams.models import Team

@pytest.fixture
def enterprise_plan_with_price():
    plan, _ = BillingPlan.objects.get_or_create(key='enterprise', defaults={'name': 'Enterprise'})
    plan.stripe_price_monthly_id = 'price_test_enterprise'
    plan.save()
    return plan

@pytest.fixture
def team_with_subscription(db):
    team = Team.objects.create(
        key='test_team', 
        name='Test Team',
        billing_plan='business',
        billing_plan_limits={
            'stripe_subscription_id': 'sub_test_123',
            'stripe_customer_id': 'cus_test_123',
            'cancel_at_period_end': False
        }
    )
    return team

@pytest.mark.django_db
def test_handle_subscription_updated_price_id_match(enterprise_plan_with_price, team_with_subscription):
    """Test that subscription update with matching Price ID updates the team plan."""
    
    # Mock Subscription object
    mock_sub = MagicMock()
    mock_sub.id = 'sub_test_123'
    mock_sub.customer = 'cus_test_123'
    mock_sub.status = 'active'
    mock_sub.current_period_end = 1770336664
    mock_sub.metadata = {}
    mock_sub.cancel_at_period_end = False    
    
    # Mock Item with Price ID
    mock_item = MagicMock()
    mock_item.price.id = 'price_test_enterprise'
    mock_sub.items.data = [mock_item]
    
    # Execute
    handle_subscription_updated(mock_sub)
    
    # Verify
    team_with_subscription.refresh_from_db()
    assert team_with_subscription.billing_plan == 'enterprise'
    assert team_with_subscription.billing_plan_limits['max_products'] == enterprise_plan_with_price.max_products

@pytest.mark.django_db
def test_handle_subscription_updated_cancel_at_period_end_sync(enterprise_plan_with_price, team_with_subscription):
    """Test that cancel_at_period_end flag is synced from subscription."""
    
    mock_sub = MagicMock()
    mock_sub.id = 'sub_test_123'
    mock_sub.customer = 'cus_test_123'
    mock_sub.status = 'active'
    mock_sub.items.data = [MagicMock(price=MagicMock(id='price_test_enterprise'))]
    mock_sub.cancel_at_period_end = True
    
    handle_subscription_updated(mock_sub)
    
    team_with_subscription.refresh_from_db()
    assert team_with_subscription.billing_plan_limits['cancel_at_period_end'] is True
