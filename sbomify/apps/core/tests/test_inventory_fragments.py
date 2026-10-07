"""Inventory result requests retain the surrounding page and filter controls."""

import re

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Member


def _titles(content: bytes) -> list[str]:
    """Every document title the response carries, as the browser would read it."""
    return [" ".join(match.split()) for match in re.findall(r"<title>(.*?)</title>", content.decode(), re.S)]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["products", "components", "releases"])
def test_result_request_returns_only_results(
    client: Client, sample_team_with_owner_member: Member, mocker: MockerFixture, kind: str
) -> None:
    member = sample_team_with_owner_member
    setup_authenticated_client_session(client, member.team, member.user)
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)
    response = client.get(
        reverse(f"core:{kind}_dashboard"),
        {"search": "example", "sort": "name", "direction": "desc"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="inventory-content-results",
    )
    assert response.status_code == 200
    assert b'id="inventory-content-results"' in response.content
    assert re.search(rb'name="direction"\s+value="desc"', response.content)
    assert b"<html" not in response.content
    assert b"<form" not in response.content
    assert b'aria-label="Product inventory"' not in response.content
    assert "HX-Target" in response["Vary"]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["products", "components", "releases"])
def test_tab_request_returns_panel_without_replacing_navigation(
    client: Client, sample_team_with_owner_member: Member, mocker: MockerFixture, kind: str
) -> None:
    member = sample_team_with_owner_member
    setup_authenticated_client_session(client, member.team, member.user)
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)
    # Each tab is its own URL; a legacy ?view= link redirects instead (see
    # test_legacy_inventory_links_redirect_with_filters).
    response = client.get(
        reverse(f"core:{kind}_dashboard"),
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="inventory-panel",
    )
    assert response.status_code == 200
    assert f'data-inventory-kind="{kind}"'.encode() in response.content
    assert b'id="inventory-panel"' in response.content
    assert b'id="inventory-content-filters"' in response.content
    assert b'id="inventory-content-results"' in response.content
    assert b'aria-label="Product inventory"' not in response.content
    assert b"<html" not in response.content
    assert "HX-Target" in response["Vary"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "title"),
    [
        ("products", "Products · sbomify"),
        ("components", "Components · Products · sbomify"),
        ("releases", "Releases · Products · sbomify"),
    ],
)
def test_a_tab_swap_renames_the_page(
    client: Client, sample_team_with_owner_member: Member, mocker: MockerFixture, kind: str, title: str
) -> None:
    """A tab is its own page, so the browser must stop calling all three Products."""
    member = sample_team_with_owner_member
    setup_authenticated_client_session(client, member.team, member.user)
    mocker.patch("sbomify.apps.billing.config.needs_plan_selection", return_value=False)
    url = reverse(f"core:{kind}_dashboard")

    assert _titles(client.get(url).content) == [title]

    # htmx takes a root-level <title> out of a fragment, so the tab swap carries
    # the same name the full render gives the page.
    for target in ("inventory-panel", "inventory-content"):
        fragment = client.get(url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET=target)
        assert _titles(fragment.content) == [title], target

    # A results-only swap never leaves the tab, so it has no name to change.
    results = client.get(url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="inventory-content-results")
    assert b"<title>" not in results.content
