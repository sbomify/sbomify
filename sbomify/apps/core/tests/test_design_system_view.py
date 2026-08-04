from __future__ import annotations

import importlib

import pytest
from django.test import Client
from django.urls import NoReverseMatch, URLResolver, clear_url_caches, reverse

import sbomify.apps.core.urls
import sbomify.urls
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session


def _reload_urlconf() -> None:
    """Re-import core.urls (its dev-only routes depend on DEBUG at import time).

    The root urlconf can't be reloaded (the ninja API singleton rejects a second
    registration), so instead drop the cached patterns on its nested resolvers.
    """
    importlib.reload(sbomify.apps.core.urls)
    for pattern in sbomify.urls.urlpatterns:
        if isinstance(pattern, URLResolver):
            pattern.__dict__.pop("url_patterns", None)
    clear_url_caches()


def _debug_urlconf_fixture(debug: bool):
    @pytest.fixture
    def fixture(settings):
        original = settings.DEBUG
        settings.DEBUG = debug
        _reload_urlconf()
        yield
        settings.DEBUG = original
        _reload_urlconf()

    return fixture


debug_mode = _debug_urlconf_fixture(True)
production_mode = _debug_urlconf_fixture(False)


@pytest.mark.django_db
class TestDesignSystemView:
    """The design-system gallery only exists in local development (DEBUG=True)."""

    def test_route_not_registered_in_production(self, production_mode, sample_team_with_owner_member):
        member = sample_team_with_owner_member
        member.user.is_superuser = True
        member.user.save()
        client = Client()
        setup_authenticated_client_session(client, member.team, member.user)
        with pytest.raises(NoReverseMatch):
            reverse("core:design_system")
        response = client.get("/design-system/")
        assert response.status_code == 404

    def test_debug_mode_anonymous_user_redirected_to_login(self, debug_mode):
        client = Client()
        response = client.get(reverse("core:design_system"))
        assert response.status_code == 302

    def test_debug_mode_renders_for_authenticated_user(self, debug_mode, sample_team_with_owner_member):
        member = sample_team_with_owner_member
        client = Client()
        setup_authenticated_client_session(client, member.team, member.user)
        response = client.get(reverse("core:design_system"))
        assert response.status_code == 200
        assert b"sbomify Design System" in response.content
