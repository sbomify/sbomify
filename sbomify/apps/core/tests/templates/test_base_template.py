import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.utils import get_user_teams


@pytest.mark.django_db
class TestBaseTemplate:
    def test_base_template_components(self, client: Client, sample_user, ensure_billing_plans):
        """Test that base template components are rendered correctly"""
        client.login(username=sample_user.username, password="test")  # nosec B106

        # Create team with wizard completed to avoid redirect
        team = Team.objects.create(name="Test Team", has_completed_wizard=True)
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(user=sample_user, team=team, role="owner", is_default_team=True)

        # Set up session with completed wizard
        user_teams = get_user_teams(sample_user)
        session = client.session
        session["user_teams"] = user_teams
        session["current_team"] = {"key": team.key, **user_teams[team.key]}
        session.save()

        response = client.get(reverse("core:dashboard"))

        content = response.content.decode()

        # Test navigation elements
        assert '<nav id="sidebar"' in content
        assert 'class="sidebar js-sidebar"' in content

        # Test user info is present in dropdown (updated for new structure)
        assert any([sample_user.username in content, 'href="/logout"' in content, "Log out" in content])

        # Test basic structure
        assert "<!doctype html>" in content.lower()
        assert "<head" in content
        assert "<body" in content

    def test_unauthenticated_redirect(self, client: Client):
        """Test that unauthenticated users are redirected to login"""
        response = client.get(reverse("core:dashboard"))
        assert response.status_code == 302
        assert "login" in response.url

    def test_sidebar_active_states(self, client: Client, sample_user, ensure_billing_plans):
        """Test that sidebar active states are set correctly"""
        client.login(username=sample_user.username, password="test")  # nosec B106

        # Ensure the user has a team with completed wizard
        team = Team.objects.create(name="Test Team", has_completed_wizard=True)
        team.key = number_to_random_token(team.pk)
        team.save()

        # Create membership
        Member.objects.create(user=sample_user, team=team, role="owner", is_default_team=True)

        # Properly set up session data using the utility function
        user_teams = get_user_teams(sample_user)
        session = client.session
        session["user_teams"] = user_teams

        # Set current team to the team we just created
        session["current_team"] = {
            "key": team.key,
            **user_teams[team.key]
        }
        session.save()

        response = client.get(reverse("core:dashboard"))
        content = response.content.decode()

        # Check for active state in new sidebar structure (li element with active class)
        assert "sidebar-item active" in content
        assert "Dashboard</span>" in content

        # Test other navigation items present
        assert "Workspace</span>" in content
        assert "Products</span>" in content
        assert "Projects</span>" in content
        assert "Components</span>" in content
