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
    session["current_workspace"]["has_completed_wizard"] = True
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
    # Every internal role may open the API tokens tab, so a member keeps that example.
    assert "api key" in {item.get("query") for item in json.loads(member_suggestions[1])}

    member.role = "operator"
    member.save(update_fields=["role"])
    operator_page = client.get(reverse("core:dashboard"))
    assert operator_page.status_code == 200
    operator_suggestions = re.search(
        rb'<script id="navbar-search-suggestions" type="application/json">(.*?)</script>', operator_page.content
    )
    assert operator_suggestions
    assert "new release" not in {item.get("query") for item in json.loads(operator_suggestions[1])}

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


def test_cryptography_is_reachable_from_the_rail(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    """The workspace crypto page lost its only entry point in the prototype
    migration: the Overview quick-actions tile that used to link to it was
    replaced by a creation-only strip, and nothing took its place. The page
    kept working, so only a link check catches it."""
    member = sample_team_with_owner_member
    workspace = member.team
    setup_authenticated_client_session(client, workspace, sample_user)
    session = client.session
    session["current_workspace"]["has_completed_wizard"] = True
    session.save()
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)

    destination = reverse("sboms:workspace_crypto", args=[workspace.key]).encode()

    owner_page = client.get(reverse("core:dashboard"))
    assert owner_page.status_code == 200
    assert b'aria-label="Cryptography"' in owner_page.content
    assert destination in owner_page.content

    # WorkspaceCryptoView admits every role but guest, so a contributor keeps it.
    member.role = "member"
    member.save(update_fields=["role"])
    contributor_page = client.get(reverse("core:dashboard"))
    assert contributor_page.status_code == 200
    assert b'aria-label="Cryptography"' in contributor_page.content
    assert destination in contributor_page.content


def test_trends_page_hands_its_filters_to_the_fragment_it_fetches(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    """A bookmarked or shared Trends link opened on the defaults.

    The page fetches its own content, so a filter in the address bar has to
    travel with that fetch. The chart view is not one of them: only the browser
    reads that, and sending it would mean the server rendered it too.
    """
    workspace = sample_team_with_owner_member.team
    setup_authenticated_client_session(client, workspace, sample_user)
    session = client.session
    session["current_workspace"]["has_completed_wizard"] = True
    session.save()
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)
    fragment = reverse("vulnerability_scanning:vulnerability_trends")

    bare = client.get(reverse("core:dashboard_trends"))
    assert f'hx-get="{fragment}?show_product_filter=true"'.encode() in bare.content

    filtered = client.get(
        reverse("core:dashboard_trends"),
        {"days": "7", "release_id": "", "chart": "severity", "not_a_filter": "x"},
    )
    assert filtered.status_code == 200
    hx_get = re.search(rb'hx-get="([^"]+)"', filtered.content)
    assert hx_get
    assert hx_get[1].decode() == f"{fragment}?show_product_filter=true&amp;release_id=&amp;days=7"


def test_sidebar_links_point_at_the_workspace_the_page_is_about(
    client: Client, sample_user: User, sample_team_with_owner_member: Member, mocker: MockerFixture
) -> None:
    """The capability flags describe the URL's workspace, so the links have to go there too.

    Built from the session's workspace, they sent an operator on another
    workspace's page to links its flags were never checked against.
    """
    from sbomify.apps.teams.models import Team

    other = Team.objects.create(name="Other workspace")
    Member.objects.create(team=other, user=sample_user, role="operator")
    setup_authenticated_client_session(client, sample_team_with_owner_member.team, sample_user)
    session = client.session
    session["current_workspace"]["has_completed_wizard"] = True
    session.save()
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)

    page = client.get(reverse("vulnerability_scanning:vulnerability_scans", kwargs={"team_key": other.key}))

    assert page.status_code == 200
    sidebar = re.search(r'<aside id="sidebar".*?</aside>', page.content.decode(), re.S)
    assert sidebar
    for url in (
        reverse("vulnerability_scanning:vulnerability_scans", kwargs={"team_key": other.key}),
        reverse("sboms:workspace_crypto", kwargs={"team_key": other.key}),
        reverse("teams:team_settings_tab", kwargs={"team_key": other.key, "tab": "tokens"}),
        reverse("teams:team_settings", kwargs={"team_key": other.key}),
    ):
        assert f'href="{url}"' in sidebar[0], url
        # The switcher lists the session's workspace as current; only these links must not.
        assert f'href="{url.replace(other.key, sample_team_with_owner_member.team.key)}"' not in sidebar[0], url
