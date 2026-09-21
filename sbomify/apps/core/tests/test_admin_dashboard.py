"""Tests for admin dashboard statistics."""

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.core.admin import admin_site
from sbomify.apps.core.models import Component, Product
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
    """Create products and components for testing 30-day metrics."""
    now = timezone.now()
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
        "recent_component": recent_component,
        "old_component": old_component,
    }

    # Cleanup
    recent_product.delete()
    old_product.delete()
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


@pytest.mark.django_db
class TestPayingWorkspaceDefinition:
    """The free community plan must never be counted as revenue.

    ``_setup_community_plan`` writes ``subscription_status="active"`` onto
    every community workspace, so a bare status filter reported the whole
    install as paying. The fixtures above could not catch it: their community
    workspaces carry ``billing_plan_limits=None``, which production never
    writes.
    """

    def test_community_workspace_is_not_paying(self, db):
        from sbomify.apps.billing.services.workspace_status import paying_workspaces

        team = Team.objects.create(
            name="Community As Production Writes It",
            billing_plan="community",
            billing_plan_limits={
                "max_products": 1,
                "max_components": 5,
                "subscription_status": "active",
                "last_updated": timezone.now().isoformat(),
            },
        )

        assert paying_workspaces().count() == 0

        team.delete()

    def test_business_workspace_with_live_subscription_is_paying(self, db):
        from sbomify.apps.billing.services.workspace_status import paying_workspaces

        team = Team.objects.create(
            name="Real Customer",
            billing_plan="business",
            billing_plan_limits={
                "subscription_status": "active",
                "stripe_subscription_id": "sub_real_123",
                "stripe_customer_id": "cus_real_123",
            },
        )

        assert paying_workspaces().count() == 1

        team.delete()

    def test_enterprise_without_stripe_ids_is_still_paying(self, db):
        """Enterprise is sales-led, so it may be billed outside Stripe."""
        from sbomify.apps.billing.services.workspace_status import paying_workspaces

        team = Team.objects.create(
            name="Contract Customer",
            billing_plan="enterprise",
            billing_plan_limits={"subscription_status": "active"},
        )

        assert paying_workspaces().count() == 1

        team.delete()

    def test_dashboard_excludes_community_from_paying_count(self, db, dashboard_stats_teams):
        """The headline card, end to end, with a production-shaped community row."""
        from django.core.cache import cache

        community = Team.objects.create(
            name="Another Community Workspace",
            billing_plan="community",
            billing_plan_limits={
                "subscription_status": "active",
                "max_products": 1,
                "max_components": 5,
            },
        )

        cache.delete("admin_dashboard_stats")
        stats = admin_site.get_dashboard_stats()

        # Six workspaces exist, only the business one with an active
        # subscription pays.
        assert stats["teams"] == 6
        assert stats["teams_active"] == 1

        community.delete()


@pytest.mark.django_db
class TestUsersPerWorkspace:
    """The chart claims to show the largest workspaces, so it must be ordered."""

    def test_workspaces_are_ordered_by_member_count(self, db, django_user_model):
        from django.core.cache import cache

        from sbomify.apps.teams.models import Member

        small = Team.objects.create(name="Small Workspace")
        large = Team.objects.create(name="Large Workspace")

        for index in range(3):
            user = django_user_model.objects.create_user(
                username=f"ordering-user-{index}",
                email=f"ordering-user-{index}@example.com",
                password="x",
            )
            Member.objects.create(team=large, user=user, role="member")

        solo = django_user_model.objects.create_user(
            username="ordering-solo",
            email="ordering-solo@example.com",
            password="x",
        )
        Member.objects.create(team=small, user=solo, role="member")

        cache.delete("admin_dashboard_stats")
        stats = admin_site.get_dashboard_stats()

        counts = {row["name"]: row["user_count"] for row in stats["users_per_team"]}
        assert counts["Large Workspace"] == 3
        assert counts["Small Workspace"] == 1

        names = [row["name"] for row in stats["users_per_team"]]
        assert names.index("Large Workspace") < names.index("Small Workspace")

        small.delete()
        large.delete()
