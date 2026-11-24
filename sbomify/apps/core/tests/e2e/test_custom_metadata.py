"""Custom metadata edits preserve arbitrary string keys."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from sbomify.apps.core.models import Component
from sbomify.apps.teams.models import Workspace


@pytest.mark.django_db
def test_component_editor_saves_object_property_names(
    authenticated_page: Page, team_with_business_plan: Workspace
) -> None:
    """JavaScript Object property names are valid metadata keys, including after reopening."""
    component = Component.objects.create(
        team=team_with_business_plan,
        name="Metadata keys",
        custom_metadata={"__proto__": "prototype value", "constructor": "constructor value", "toString": "text value"},
    )
    page = authenticated_page
    page.goto(reverse("core:component_details", kwargs={"component_id": component.pk}))
    page.get_by_role("button", name="Component actions", exact=True).click()
    page.get_by_text("Metadata…", exact=True).click()
    page.get_by_role("button", name="Edit Metadata", exact=True).click()
    editor = page.locator(".component-meta-info-editor")
    expect(editor.get_by_role("textbox", name="Key 1", exact=True)).to_have_value("__proto__")
    editor.get_by_role("textbox", name="Value 1", exact=True).fill("updated prototype value")
    save = editor.get_by_role("button", name="Save Component Metadata", exact=True)
    expect(save).to_be_enabled()
    with page.expect_response(
        lambda r: r.request.method == "PATCH" and r.url.endswith(f"/{component.pk}/metadata")
    ) as sent:
        save.click()
    assert sent.value.status == 204
    component.refresh_from_db()
    assert component.custom_metadata == {
        "__proto__": "updated prototype value",
        "constructor": "constructor value",
        "toString": "text value",
    }
    page.reload()
    page.get_by_role("button", name="Component actions", exact=True).click()
    page.get_by_text("Metadata…", exact=True).click()
    page.get_by_role("button", name="Edit Metadata", exact=True).click()
    expect(editor.get_by_role("textbox", name="Value 1", exact=True)).to_have_value("updated prototype value")
    expect(editor.get_by_role("button", name="Save Component Metadata", exact=True)).to_be_enabled()


@pytest.mark.django_db
@pytest.mark.parametrize("width", [576, 1920])
def test_product_metadata_card_save_and_reopen(
    authenticated_page: Page, team_with_business_plan: Workspace, width: int
) -> None:
    """The HTMX card reopens the saved values rather than the original JSON script."""
    from sbomify.apps.core.models import Product

    product = Product.objects.create(
        team=team_with_business_plan, name="Product metadata", custom_metadata={"owner": "old"}
    )
    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(reverse("core:product_details", kwargs={"product_id": product.pk}))
    page.get_by_role("tab", name="Metadata", exact=True).click()
    panel = page.locator("#product-custom-metadata-panel")
    panel.get_by_role("button", name="Edit", exact=True).click()
    panel.get_by_role("textbox", name="Value 1", exact=True).fill("new owner")
    panel.get_by_role("button", name="Save", exact=True).click()
    expect(panel.get_by_text("new owner", exact=True)).to_be_visible()
    product.refresh_from_db()
    assert product.custom_metadata == {"owner": "new owner"}
    panel.get_by_role("button", name="Edit", exact=True).click()
    expect(panel.get_by_role("textbox", name="Value 1", exact=True)).to_have_value("new owner")
