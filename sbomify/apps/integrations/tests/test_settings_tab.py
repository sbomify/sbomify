"""The Integrations section inside workspace settings."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member
from sbomify.apps.teams.settings_tabs import TABS_BY_KEY, visible_tabs
from sbomify.apps.teams.utils import ALLOWED_TABS, redirect_to_team_settings

pytestmark = pytest.mark.django_db


class TestTabRegistration:
    def test_the_tab_exists(self) -> None:
        assert "integrations" in TABS_BY_KEY
        assert TABS_BY_KEY["integrations"].template_path == "teams/team_settings_tabs/integrations.html.j2"

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_owners_and_admins_see_it(self, role) -> None:
        assert "integrations" in [tab.key for tab in visible_tabs(role, billing_enabled=True)]

    @pytest.mark.parametrize("role", ["member", "guest", None])
    def test_nobody_below_administer_sees_it(self, role) -> None:
        """Connecting an account and publishing what it says are both outward-facing."""
        assert "integrations" not in [tab.key for tab in visible_tabs(role, billing_enabled=True)]

    def test_it_is_reachable_by_the_old_fragment_links(self, sample_team_with_owner_member) -> None:  # noqa: F811
        """#integrations was already an allowed tab name, so the redirect must land on the page."""
        assert "integrations" in ALLOWED_TABS
        response = redirect_to_team_settings(sample_team_with_owner_member.team.key, "integrations")
        assert response.url.endswith("/settings/integrations")


class TestTabPage:
    def test_the_section_renders_and_loads_its_panel(self, sample_team_with_owner_member) -> None:  # noqa: F811
        team = sample_team_with_owner_member.team
        client = Client()
        setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

        response = client.get(reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "integrations"}))

        assert response.status_code == 200
        assert reverse("integrations:panel", kwargs={"team_key": team.key}).encode() in response.content

    def test_a_member_is_sent_to_a_section_they_may_open(self, sample_team_with_owner_member, guest_user) -> None:  # noqa: F811
        team = sample_team_with_owner_member.team
        Member.objects.create(user=guest_user, team=team, role="member")
        client = Client()
        setup_authenticated_client_session(client, team, guest_user)

        response = client.get(reverse("teams:team_settings_tab", kwargs={"team_key": team.key, "tab": "integrations"}))

        assert response.status_code == 302
        assert not response.url.endswith("/settings/integrations")


class TestSpotlight:
    def test_the_palette_can_reach_it(self) -> None:
        import json
        from pathlib import Path

        from django.conf import settings

        data = json.loads(
            (Path(settings.BASE_DIR) / "sbomify" / "apps" / "core" / "data" / "spotlight_destinations.json").read_text()
        )
        entry = next(d for d in data["destinations"] if d["title"] == "Integrations")

        assert entry["fragment"] == "integrations"
        assert "vanta" in entry["keywords"]
