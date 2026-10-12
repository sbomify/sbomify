"""Secondary features must not compete with the page's initial content."""

import pytest
from playwright.sync_api import Page, expect

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


@pytest.mark.django_db
def test_publishers_load_on_open_and_retry_after_failure(authenticated_page: Page, sbom_component_details) -> None:
    page = authenticated_page
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    page.goto(f"/component/{sbom_component_details.id}/")
    page.wait_for_load_state("networkidle")
    # Use the endpoint rendered by Django so this also checks the modal wiring.
    loader = page.locator("#trustedPublishersModal [hx-get]")
    publishers_url = loader.get_attribute("hx-get")
    assert publishers_url
    assert not any(publishers_url in url for url in requests)
    assert not any("chart-setup-" in url or "JsBarcode-" in url for url in requests)

    page.route(f"**{publishers_url}", lambda route: route.fulfill(status=503, body="Unavailable"), times=1)
    with page.expect_response(lambda response: publishers_url in response.url and response.status == 503):
        page.evaluate("window.dispatchEvent(new CustomEvent('open-trusted-publishers'))")
    expect(page.locator("#toast-container")).to_contain_text("Request Failed")
    page.keyboard.press("Escape")
    page.evaluate("window.dispatchEvent(new CustomEvent('open-trusted-publishers'))")
    expect(page.locator("#trusted-publishers-section")).to_be_visible()
    assert len([url for url in requests if publishers_url in url]) == 2
    page.keyboard.press("Escape")
    page.evaluate("window.dispatchEvent(new CustomEvent('open-trusted-publishers'))")
    expect(page.locator("#trusted-publishers-section")).to_be_visible()
    assert len([url for url in requests if publishers_url in url]) == 2
