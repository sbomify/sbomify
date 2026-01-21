"""Tests for admin dashboard statistics."""

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.core.admin import admin_site
from sbomify.apps.core.models import Component, Product, Project, User
from sbomify.apps.teams.models import Invitation, Team


@pytest.fixture
def dashboard_stats_teams(db):
    """Create teams with various subscription statuses for testing."""
    teams = []
    
    # Team with active subscription
    team_active = Team.objects.create(
        name="Active Team",
        billing_plan="business",
        billing_plan_limits={
            "subscription_status": "active",
            "stripe_subscription_id": "sub_active_123",
            "stripe_customer_id": "cus_active_123",
        },
    )
    teams.append(team_active)
    
    # Team with trialing subscription
    team_trialing = Team.objects.create(
        name="Trialing Team",
        billing_plan="business",
        billing_plan_limits={
            "subscription_status": "trialing",
            "stripe_subscription_id": "sub_trial_123",
            "stripe_customer_id": "cus_trial_123",
        },
    )
    teams.append(team_trialing)
    
    # Team with past_due subscription
    team_past_due = Team.objects.create(
        name="Past Due Team",
        billing_plan="business",
        billing_plan_limits={
            "subscription_status": "past_due",
            "stripe_subscription_id": "sub_pastdue_123",
            "stripe_customer_id": "cus_pastdue_123",
        },
    )
    teams.append(team_past_due)
    
    # Team with canceled subscription
    team_canceled = Team.objects.create(
        name="Canceled Team",
        billing_plan="community",
        billing_plan_limits={
            "subscription_status": "canceled",
            "stripe_subscription_id": "sub_canceled_123",
            "stripe_customer_id": "cus_canceled_123",
        },
    )
    teams.append(team_canceled)
    
    # Team with no billing (community)
    team_community = Team.objects.create(
        name="Community Team",
        billing_plan="community",
        billing_plan_limits=None,
    )
    teams.append(team_community)
    
    yield teams
    
    # Cleanup
    for team in teams:
        team.delete()


@pytest.fixture
def dashboard_stats_content(db, dashboard_stats_teams):
    """Create products, projects, and components for testing 30-day metrics."""
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)
    
    team = dashboard_stats_teams[0]
    
    # Create recent products (within 30 days)
    recent_product = Product.objects.create(
        name="Recent Product",
        team=team,
    )
    
    # Create old product (more than 30 days ago)
    old_product = Product.objects.create(
        name="Old Product",
        team=team,
    )
    # Manually update created_at to be older
    Product.objects.filter(pk=old_product.pk).update(created_at=sixty_days_ago)
    
    # Create recent project
    recent_project = Project.objects.create(
        name="Recent Project",
        team=team,
    )
    
    # Create old project
    old_project = Project.objects.create(
        name="Old Project",
        team=team,
    )
    Project.objects.filter(pk=old_project.pk).update(created_at=sixty_days_ago)
    
    # Create recent component
    recent_component = Component.objects.create(
        name="Recent Component",
        team=team,
    )
    
    # Create old component
    old_component = Component.objects.create(
        name="Old Component",
        team=team,
    )
    Component.objects.filter(pk=old_component.pk).update(created_at=sixty_days_ago)
    
    yield {
        "recent_product": recent_product,
        "old_product": old_product,
        "recent_project": recent_project,
        "old_project": old_project,
        "recent_component": recent_component,
        "old_component": old_component,
    }
    
    # Cleanup
    recent_product.delete()
    old_product.delete()
    recent_project.delete()
    old_project.delete()
    recent_component.delete()
    old_component.delete()


@pytest.fixture
def dashboard_stats_invitations(db, dashboard_stats_teams):
    """Create invitations for testing pending/expired metrics."""
    now = timezone.now()
    team = dashboard_stats_teams[0]
    
    # Pending invitation (expires in future)
    pending_invitation = Invitation.objects.create(
        team=team,
        email="pending@example.com",
        role="admin",
        expires_at=now + timedelta(days=7),
    )
    
    # Expired invitation (expired in past)
    expired_invitation = Invitation.objects.create(
        team=team,
        email="expired@example.com",
        role="admin",
        expires_at=now - timedelta(days=1),
    )
    
    yield {
        "pending": pending_invitation,
        "expired": expired_invitation,
    }
    
    # Cleanup
    pending_invitation.delete()
    expired_invitation.delete()


@pytest.mark.django_db
class TestDashboardStats:
    """Tests for dashboard statistics."""
    
    def test_teams_active_only_counts_active_subscriptions(self, dashboard_stats_teams):
        """Test that teams_active only counts teams with subscription_status='active'."""
        # Clear cache to ensure fresh stats
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should only count the one team with "active" status
        assert stats["teams_active"] == 1
    
    def test_teams_trialing_only_counts_trialing_subscriptions(self, dashboard_stats_teams):
        """Test that teams_trialing only counts teams with subscription_status='trialing'."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should only count the one team with "trialing" status
        assert stats["teams_trialing"] == 1
    
    def test_teams_past_due_only_counts_past_due_subscriptions(self, dashboard_stats_teams):
        """Test that teams_past_due only counts teams with subscription_status='past_due'."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should only count the one team with "past_due" status
        assert stats["teams_past_due"] == 1
    
    def test_teams_canceled_only_counts_canceled_subscriptions(self, dashboard_stats_teams):
        """Test that teams_canceled only counts teams with subscription_status='canceled'."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should only count the one team with "canceled" status
        assert stats["teams_canceled"] == 1
    
    def test_total_teams_counts_all_teams(self, dashboard_stats_teams):
        """Test that total teams count includes all teams."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should count all 5 teams
        assert stats["teams"] == 5
    
    def test_products_30d_only_counts_recent_products(self, dashboard_stats_content):
        """Test that products_30d only counts products created in last 30 days."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should only count the recent product
        assert stats["products_30d"] == 1
        # Total products should be 2
        assert stats["products"] == 2
    
    def test_projects_30d_only_counts_recent_projects(self, dashboard_stats_content):
        """Test that projects_30d only counts projects created in last 30 days."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should only count the recent project
        assert stats["projects_30d"] == 1
        # Total projects should be 2
        assert stats["projects"] == 2
    
    def test_components_30d_only_counts_recent_components(self, dashboard_stats_content):
        """Test that components_30d only counts components created in last 30 days."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should only count the recent component
        assert stats["components_30d"] == 1
        # Total components should be 2
        assert stats["components"] == 2
    
    def test_pending_invitations_only_counts_non_expired(self, dashboard_stats_invitations):
        """Test that pending_invitations only counts invitations that haven't expired."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should only count the pending invitation
        assert stats["pending_invitations"] == 1
    
    def test_expired_invitations_only_counts_expired(self, dashboard_stats_invitations):
        """Test that expired_invitations only counts invitations that have expired."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        stats = admin_site.get_dashboard_stats()
        
        # Should only count the expired invitation
        assert stats["expired_invitations"] == 1
    
    def test_stats_are_cached(self, dashboard_stats_teams):
        """Test that stats are cached after first call."""
        from django.core.cache import cache
        cache.delete("admin_dashboard_stats")
        
        # First call should populate cache
        stats1 = admin_site.get_dashboard_stats()
        
        # Create a new team
        new_team = Team.objects.create(
            name="New Team",
            billing_plan="business",
            billing_plan_limits={"subscription_status": "active"},
        )
        
        # Second call should return cached results
        stats2 = admin_site.get_dashboard_stats()
        
        # Stats should be the same (cached)
        assert stats1["teams_active"] == stats2["teams_active"]
        
        # Cleanup
        new_team.delete()
