"""Pages follow workspace socket messages without a reload.

Each test changes the database behind an open page, then sends the message the
server would, the way the socket store sends it: a ws:message plus its typed
twin. What the page shows afterwards is what a reader in another session sees.
"""

from typing import Any

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.models import Component, Release
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


def _announce(page: Page, detail: dict[str, Any]) -> None:
    page.evaluate(
        """(detail) => {
            window.dispatchEvent(new CustomEvent('ws:message', { detail }));
            window.dispatchEvent(new CustomEvent(`ws:${detail.type}`, { detail }));
        }""",
        detail,
    )


@pytest.mark.django_db
def test_the_release_header_follows_an_edit_made_elsewhere(
    authenticated_page: Page,
    product_details,  # noqa: F811
) -> None:
    page = authenticated_page
    release = Release.objects.get(product=product_details, name="v1.0.0")
    page.goto(f"/product/{product_details.id}/release/{release.id}/")
    page.wait_for_load_state("networkidle")
    header = page.locator("#release-header")
    expect(header.get_by_role("heading", level=1)).to_contain_text("v1.0.0")

    Release.objects.filter(pk=release.pk).update(name="v1.0.0-renamed")
    _announce(page, {"type": "release_updated", "release_id": release.id, "product_id": product_details.id})

    expect(header.get_by_role("heading", level=1)).to_contain_text("v1.0.0-renamed")


@pytest.mark.django_db
def test_a_deleted_release_sends_the_reader_back_to_its_product(
    authenticated_page: Page,
    product_details,  # noqa: F811
) -> None:
    page = authenticated_page
    release = Release.objects.get(product=product_details, name="v1.0.0")
    page.goto(f"/product/{product_details.id}/release/{release.id}/")
    page.wait_for_load_state("networkidle")

    _announce(page, {"type": "release_deleted", "release_id": release.id, "product_id": product_details.id})

    page.wait_for_url(f"**/product/{product_details.id}/")


@pytest.mark.django_db
def test_the_component_header_follows_a_rename_made_elsewhere(
    authenticated_page: Page,
    dashboard,  # noqa: F811
) -> None:
    page = authenticated_page
    component = dashboard["sboms"][0].component
    page.goto(f"/component/{component.id}/")
    page.wait_for_load_state("networkidle")
    heading = page.locator("#component-header").get_by_role("heading", level=1)
    expect(heading).to_contain_text(component.name)

    Component.objects.filter(pk=component.pk).update(name="Renamed elsewhere")
    _announce(page, {"type": "component_updated", "component_id": component.id, "name": "Renamed elsewhere"})

    expect(heading).to_contain_text("Renamed elsewhere")


@pytest.mark.django_db
def test_the_overview_repaints_when_something_it_counts_changes(
    authenticated_page: Page,
    dashboard,  # noqa: F811
) -> None:
    page = authenticated_page
    page.goto("/dashboard")
    page.wait_for_load_state("networkidle")
    products = page.locator("#overview-content")
    expect(products).not_to_contain_text("Added in another session")

    dashboard["products"][0].__class__.objects.filter(pk=dashboard["products"][0].pk).update(
        name="Added in another session"
    )
    _announce(page, {"type": "product_updated", "product_id": dashboard["products"][0].id})

    expect(products).to_contain_text("Added in another session", timeout=10000)
