"""Record the contact profile editing screencast.

Drives: Dashboard → sidebar Settings → Contacts tab → Add Profile →
fill profile name, toggle default → Add Entity → fill entity details →
Add Contact ×2 with roles → Done → Create Profile.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    narrate,
    navigate_to_settings,
    pace,
    settle,
    start_on_dashboard,
    type_text,
)


def _set_entity_roles(page: Page, *, manufacturer: bool, supplier: bool, author: bool) -> None:
    """Set the entity role checkboxes.

    Plain formset checkboxes now (entities-0-is_manufacturer and friends);
    the Alpine state this helper used to drive is gone.
    """
    card = page.locator(".entity-card")
    for field, wanted in (("is_manufacturer", manufacturer), ("is_supplier", supplier), ("is_author", author)):
        card.locator(f"input[name$='-{field}']").first.set_checked(wanted)
        pace(page, 250)


@pytest.mark.django_db(transaction=True)
def profile_editing(recording_page: Page) -> None:
    page = recording_page

    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=400)
    narrate(page, "why_profile")
    navigate_to_settings(page)

    # Switch to the Contacts tab
    narrate(page, "contacts_tab")
    # Settings sections are real links now (one URL each) rather than the old
    # data-tab switcher — same matching style as
    # conftest.navigate_to_trust_center_tab.
    contacts_tab = page.locator("a.settings-tab[href$='/contact-profiles']")
    contacts_tab.wait_for(state="visible", timeout=15_000)
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
    narrate(page, "name_profile")
    name_input = page.locator("input[placeholder*='Default Profile']")
    hover_and_click(page, name_input)
    pace(page, 300)
    type_text(name_input, "Pied Piper Compliance")
    pace(page, 500)

    # Tick "Set as default" — a plain checkbox since the toggle conversion.
    default_checkbox = profile_form.locator("input[name='is_default']")
    hover_and_click(page, default_checkbox)
    pace(page, 500)

    # Click "Add Entity" — the form starts with zero entities (empty state)
    narrate(page, "add_entity")
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
    narrate(page, "entity_roles")
    _set_entity_roles(page, manufacturer=True, supplier=True, author=True)
    pace(page, 300)

    # Entity name
    narrate(page, "entity_details")
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
    entity_address.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    hover_and_click(page, entity_address)
    pace(page, 200)
    type_text(entity_address, "5230 Newell Road, Palo Alto, CA 94303")
    pace(page, 400)

    # Entity website
    narrate(page, "entity_web")
    entity_website = editor.locator("textarea[placeholder*='one URL per line']")
    hover_and_click(page, entity_website)
    pace(page, 200)
    type_text(entity_website, "https://piedpiper.com")
    pace(page, 600)

    # --- Add first contact ---
    narrate(page, "add_contact")
    add_contact_btn = entity_card.locator("button:has-text('Add Contact')")
    add_contact_btn.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, add_contact_btn)
    pace(page, 500)

    # Fill first contact details — only one contact card exists at this point
    contact1 = entity_card.locator(".contact-card").first
    contact1.wait_for(state="visible", timeout=5_000)

    narrate(page, "contact_one")
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

    narrate(page, "contact_roles")
    # Check Author, Security, Technical roles for first contact
    contact1.locator("input[name$='-is_author']").check()
    pace(page, 250)
    contact1.locator("input[name$='-is_security_contact']").check()
    pace(page, 250)
    contact1.locator("input[name$='-is_technical_contact']").check()
    pace(page, 500)

    narrate(page, "contact_two")
    # --- Add second contact ---
    add_contact_btn.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
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

    narrate(page, "done")
    # --- Done editing entity ---
    done_btn = entity_card.locator("button:has-text('Done')")
    done_btn.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, done_btn)
    pace(page, 800)

    narrate(page, "outro")
    # --- Submit the form ---
    create_btn = page.locator("button[type='submit']:has-text('Create Profile')")
    create_btn.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    pace(page, 300)
    hover_and_click(page, create_btn)

    # Wait for the profile list to reappear (HTMX swap after successful creation)
    content.locator("table, .tw-empty-state").first.wait_for(state="visible", timeout=15_000)
    settle(page)
