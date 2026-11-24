"""Invalid creation forms keep their data and use the shared field errors."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", ["product", "component"])
def test_create_form_recovers_from_invalid_name(authenticated_page: Page, kind: str) -> None:
    page = authenticated_page
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(reverse(f"core:{kind}_new"))
    page.get_by_role("textbox", name="Name", exact=False).fill(" ")
    if kind == "product":
        page.get_by_role("textbox", name="Description").fill("Keep these notes")
    else:
        page.get_by_role("radio", name="Document", exact=True).press("Space")
        page.get_by_role("checkbox", name="Workspace-wide component").press("Space")
    page.get_by_role("button", name=f"Create {kind}", exact=True).click()
    expect(page.get_by_text("This field is required.", exact=True)).to_be_visible()
    if kind == "product":
        expect(page.get_by_role("textbox", name="Description")).to_have_value("Keep these notes")
    else:
        expect(page.get_by_role("radio", name="Document", exact=True)).to_be_checked()
        expect(page.get_by_role("checkbox", name="Workspace-wide component")).to_be_checked()
    page.get_by_role("textbox", name="Name", exact=False).fill("Example created item")
    page.get_by_role("button", name=f"Create {kind}", exact=True).click()
    expect(page.get_by_role("heading", name="Example created item", exact=True)).to_be_visible()
    assert not errors
