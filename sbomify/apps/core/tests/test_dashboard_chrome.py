"""The shared chrome must follow live capabilities and keep working links."""

import json
import re

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.models import User
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member

pytestmark = pytest.mark.django_db


def test_chrome_reflects_demotion_without_waiting_for_fragment_cache(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    member = sample_team_with_owner_member
    workspace = member.team
    setup_authenticated_client_session(client, workspace, sample_user)
    session = client.session
    session["current_team"]["has_completed_wizard"] = True
    session.save()
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)

    owner_page = client.get(reverse("core:dashboard"))
    assert owner_page.status_code == 200
    assert b'aria-label="Compliance"' in owner_page.content
    assert b'aria-label="Plugins"' in owner_page.content
    assert b"Set up your first repository" in owner_page.content
    assert reverse("core:component_new").encode() in owner_page.content
    owner_suggestions = re.search(
        rb'<script id="navbar-search-suggestions" type="application/json">(.*?)</script>', owner_page.content
    )
    assert owner_suggestions
    assert "api key" in {item.get("query") for item in json.loads(owner_suggestions[1])}

    member.role = "member"
    member.save(update_fields=["role"])
    contributor_page = client.get(reverse("core:dashboard"))
    assert contributor_page.status_code == 200
    assert b'aria-label="Compliance"' not in contributor_page.content
    assert b'aria-label="Plugins"' not in contributor_page.content
    assert b"Set up your first repository" in contributor_page.content
    assert reverse("core:component_new").encode() in contributor_page.content
    assert b'aria-current="page"' in contributor_page.content
    assert b"<c-" not in contributor_page.content
    member_suggestions = re.search(
        rb'<script id="navbar-search-suggestions" type="application/json">(.*?)</script>', contributor_page.content
    )
    assert member_suggestions
    assert "api key" not in {item.get("query") for item in json.loads(member_suggestions[1])}

    member.role = "guest"
    member.save(update_fields=["role"])
    guest_page = client.get(reverse("core:dashboard"))
    assert guest_page.status_code == 302
    assert guest_page.url != reverse("core:dashboard")


@pytest.mark.parametrize(
    ("path", "label"),
    [
        ("/products/", "Products"),
        ("/components/", "Components"),
        ("/releases/", "Products"),
    ],
)
@pytest.mark.parametrize("partial", [False, True])
def test_inventory_navigation_tracks_selected_view(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, path: str, label: str, partial: bool
) -> None:
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_user)
    headers = {"HX-Target": "inventory-content", "HX-Request": "true"} if partial else {}
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    nav = re.search(r'(<div\s+id="inventory-navigation"[^>]*>)(.*?)</div>', response.content.decode(), re.DOTALL)
    assert nav is not None
    links = re.findall(r"<a\s[^>]*>", nav[2])
    assert [re.search(r'aria-label="([^"]+)"', link)[1] for link in links] == ["Products", "Components"]
    current = [link for link in links if 'aria-current="page"' in link]
    assert len(current) == 1
    assert f'aria-label="{label}"' in current[0]
    assert ('hx-swap-oob="outerHTML"' in nav[1]) is partial
