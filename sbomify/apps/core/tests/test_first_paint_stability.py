"""What paints first must be what stays, so a page does not shift as scripts load.

Behind Cloudflare Rocket Loader every script runs after first paint, which turns
any difference between the server's markup and Alpine's first render into a
visible jump.
"""

import re

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import User
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db

KINDS = ["products", "components", "releases"]


@pytest.mark.parametrize("kind", KINDS)
def test_only_the_current_tabs_create_button_paints_before_alpine(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, kind: str
) -> None:
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_user)
    html = client.get(reverse(f"core:{kind}_dashboard")).content.decode()

    assert "{%" not in html
    for other in KINDS:
        wrapper = re.search(rf"<span\b[^>]*x-show=\"selectedKind === '{other}'\"[^>]*>", html)
        assert wrapper is not None
        assert ("x-cloak" in wrapper[0]) is (other != kind)


@pytest.mark.parametrize(
    ("user_agent", "label"),
    [
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 15_6) AppleWebKit/537.36 Chrome/141.0 Safari/537.36", "⌘"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36", "Ctrl"),
    ],
)
def test_search_shortcut_hint_is_rendered_by_the_server(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, user_agent: str, label: str
) -> None:
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_user)
    html = client.get(reverse("core:products_dashboard"), headers={"User-Agent": user_agent}).content.decode()

    hint = re.search(r'<span x-text="shortcutLabel">([^<]*)</span>K', html)
    assert hint is not None
    assert hint[1] == label
