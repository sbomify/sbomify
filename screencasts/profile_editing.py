"""Record the contact profile editing screencast.

Drives: Dashboard → sidebar Settings → Contacts tab → Add Profile →
fill profile name, toggle default → Add Entity → fill entity details →
Add Contact ×2 with roles → Done → Create Profile.
"""

import pytest
from playwright.sync_api import Page

from conftest import hover_and_click, navigate_to_settings, pace, start_on_dashboard, type_text


def _set_entity_roles(page: Page, *, manufacturer: bool, supplier: bool, author: bool) -> None:
    """Set entity role checkboxes via Alpine data (template doesn't preserve 'checked')."""
    page.evaluate(
        """([mfg, sup, auth]) => {
        const card = document.querySelector('.entity-card');
        const data = window.Alpine.$data(card);
        data.isManufacturer = mfg;
        data.isSupplier = sup;
        data.isAuthor = auth;
    }""",
        [manufacturer, supplier, author],
    )


@pytest.mark.django_db(transaction=True)
def profile_editing(recording_page: Page) -> None:
    page = recording_page

    start_on_dashboard(page)
    navigate_to_settings(page)

    # Switch to the Contacts tab
    contacts_tab = page.locator("a[data-tab='contact-profiles']")
    hover_and_click(page, contacts_tab)
    pace(page, 800)

    # Wait for HTMX-loaded profile list content
    content = page.locator("#contact-profiles-content")
    content.locator(".tw-empty-state, table").first.wait_for(state="visible", timeout=15_000)
    pace(page, 800)

    # Click "Add Profile" — in the card header (always present)
    add_profile_btn = page.locator("button:has-text('Add Profile')").first
    hover_and_click(page, add_profile_btn)

    # Wait for the profile form to appear (HTMX swap)
    profile_form = page.locator(".profile-form")
    profile_form.wait_for(state="visible", timeout=10_000)
    pace(page, 800)

    # Fill "Profile Name"
    name_input = page.locator("input[placeholder*='Default Profile']")
    hover_and_click(page, name_input)
    pace(page, 300)
    type_text(name_input, "Pied Piper Compliance")
    pace(page, 500)

    # Toggle "Set as default"
    default_toggle = profile_form.locator("input.tw-toggle")
    hover_and_click(page, default_toggle)
    pace(page, 500)

    # Click "Add Entity" — the form starts with zero entities (empty state)
    add_entity_btn = page.locator("button:has-text('Add Entity')").first
    hover_and_click(page, add_entity_btn)
    pace(page, 600)

    # Wait for entity card to appear (Alpine clones the template)
    entity_card = page.locator(".entity-card")
    entity_card.wait_for(state="visible", timeout=5_000)
    editor = entity_card.locator(".entity-editor-content")
    editor.wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    # --- Fill entity details ---
    # The cloned template doesn't preserve checked attributes, so set roles via Alpine
    _set_entity_roles(page, manufacturer=True, supplier=True, author=True)
    pace(page, 300)

    # Entity name
    entity_name = editor.locator("input[placeholder='e.g. Acme Corporation']")
    hover_and_click(page, entity_name)
    pace(page, 200)
    type_text(entity_name, "Pied Piper Inc")
    pace(page, 400)

    # Entity email
    entity_email = editor.locator("input[placeholder='contact@example.com']")
    hover_and_click(page, entity_email)
    pace(page, 200)
    type_text(entity_email, "compliance@piedpiper.com")
    pace(page, 400)

    # Entity phone
    entity_phone = editor.locator("input[placeholder='+1 555 123 4567']")
    hover_and_click(page, entity_phone)
    pace(page, 200)
    type_text(entity_phone, "+1 650 555 0142")
    pace(page, 400)

    # Entity address
    entity_address = editor.locator("textarea[placeholder*='123 Main Street']")
    entity_address.scroll_into_view_if_needed()
    hover_and_click(page, entity_address)
    pace(page, 200)
    type_text(entity_address, "5230 Newell Road, Palo Alto, CA 94303")
    pace(page, 400)

    # Entity website
    entity_website = editor.locator("textarea[placeholder*='one URL per line']")
    hover_and_click(page, entity_website)
    pace(page, 200)
    type_text(entity_website, "https://piedpiper.com")
    pace(page, 600)

    # --- Add first contact ---
    add_contact_btn = entity_card.locator("button:has-text('Add Contact')")
    add_contact_btn.scroll_into_view_if_needed()
    pace(page, 300)
    hover_and_click(page, add_contact_btn)
    pace(page, 500)

    # Fill first contact details — only one contact card exists at this point
    contact1 = entity_card.locator(".contact-card").first
    contact1.wait_for(state="visible", timeout=5_000)

    c1_name = contact1.locator("input[aria-label='Contact Name']")
    hover_and_click(page, c1_name)
    pace(page, 200)
    type_text(c1_name, "Bertram Gilfoyle")
    pace(page, 300)

    c1_email = contact1.locator("input[aria-label='Contact Email']")
    hover_and_click(page, c1_email)
    pace(page, 200)
    type_text(c1_email, "gilfoyle@piedpiper.com")
    pace(page, 300)

    c1_phone = contact1.locator("input[aria-label='Contact Phone']")
    hover_and_click(page, c1_phone)
    pace(page, 200)
    type_text(c1_phone, "+1 650 555 0143")
    pace(page, 400)

    # Check Author, Security, Technical roles for first contact
    contact1.locator("input[name$='-is_author']").check()
    pace(page, 250)
    contact1.locator("input[name$='-is_security_contact']").check()
    pace(page, 250)
    contact1.locator("input[name$='-is_technical_contact']").check()
    pace(page, 500)

    # --- Add second contact ---
    add_contact_btn.scroll_into_view_if_needed()
    pace(page, 300)
    hover_and_click(page, add_contact_btn)
    pace(page, 500)

    # Fill second contact — target the last contact card
    contact2 = entity_card.locator(".contact-card").last
    contact2.wait_for(state="visible", timeout=5_000)

    c2_name = contact2.locator("input[aria-label='Contact Name']")
    hover_and_click(page, c2_name)
    pace(page, 200)
    type_text(c2_name, "Dinesh Chughtai")
    pace(page, 300)

    c2_email = contact2.locator("input[aria-label='Contact Email']")
    hover_and_click(page, c2_email)
    pace(page, 200)
    type_text(c2_email, "dinesh@piedpiper.com")
    pace(page, 400)

    # Check Technical role for second contact
    contact2.locator("input[name$='-is_technical_contact']").check()
    pace(page, 600)

    # --- Done editing entity ---
    done_btn = entity_card.locator("button:has-text('Done')")
    done_btn.scroll_into_view_if_needed()
    pace(page, 300)
    hover_and_click(page, done_btn)
    pace(page, 800)

    # --- Submit the form ---
    create_btn = page.locator("button[type='submit']:has-text('Create Profile')")
    create_btn.scroll_into_view_if_needed()
    pace(page, 300)
    hover_and_click(page, create_btn)

    # Wait for the profile list to reappear (HTMX swap after successful creation)
    content.locator("table, .tw-empty-state").first.wait_for(state="visible", timeout=15_000)
    pace(page, 2000)
