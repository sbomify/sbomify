import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
class TestBaseTemplate:
    def test_base_template_components(self, client: Client, sample_user):
        """Test that base template components are rendered correctly"""
        client.login(username=sample_user.username, password="test")  # nosec B106
        response = client.get(reverse("core:dashboard"))

        content = response.content.decode()

        # Test navigation elements
        assert '<nav id="sidebar"' in content
        assert 'class="sidebar js-sidebar"' in content

        # Test user info is present in dropdown (updated for new structure)
        assert any([
            sample_user.username in content,
            'href="/logout"' in content,
            'Log out' in content
        ])

        # Test basic structure
        assert "<!doctype html>" in content.lower()
        assert "<head" in content
        assert "<body" in content

    def test_unauthenticated_redirect(self, client: Client):
        """Test that unauthenticated users are redirected to login"""
        response = client.get(reverse("core:dashboard"))
        assert response.status_code == 302
        assert "login" in response.url

    def test_sidebar_active_states(self, client: Client, sample_user):
        """Test that sidebar active states are set correctly"""
        client.login(username=sample_user.username, password="test")  # nosec B106
        response = client.get(reverse("core:dashboard"))
        content = response.content.decode()
        # Check for active state in new sidebar structure (li element with active class)
        assert 'sidebar-item active' in content
        assert "Dashboard</span>" in content

        # Test other navigation items present
        assert "Workspace</span>" in content
        assert "Products</span>" in content
        assert "Projects</span>" in content
        assert "Components</span>" in content