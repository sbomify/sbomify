"""Record the party (contact profile) editing screencast.

Drives: Dashboard → sidebar Settings → Parties tab → Add party → name and
default → Add entity → roles and organization details → two contacts with
roles → Done → Create party → the party listed as the default.
"""

import pytest
from playwright.sync_api import Page

from conftest import (
    hover_and_click,
    mock_vuln_trends,
    narrate,
    navigate_to_settings,
    navigate_to_settings_tab,
    pace,
    settle,
    smooth_scroll,
    start_on_dashboard,
    type_text,
)

PARTY_NAME = "Pied Piper Compliance"


def _fill(page: Page, locator, text: str, delay: int = 60) -> None:
    hover_and_click(page, locator)
    pace(page, 150)
    type_text(locator, text, delay=delay)
    pace(page, 250)


@pytest.mark.django_db(transaction=True)
def profile_editing(recording_page: Page, pied_piper_with_sboms: dict) -> None:
    page = recording_page

    mock_vuln_trends(page)
    # The opening line plays over the splash, the dashboard and the way into
    # Settings, so the video does not open on silence.
    narrate(page, "intro")
    start_on_dashboard(page, pause_ms=300)
    navigate_to_settings(page)

    narrate(page, "parties_live_under")
    navigate_to_settings_tab(page, "contact-profiles")
    content = page.locator("#contact-profiles-content")
    content.get_by_text("No parties yet").wait_for(state="visible", timeout=15_000)

    add_party = page.get_by_role("button", name="Add party")
    hover_and_click(page, add_party)
    profile_form = page.locator(".profile-form")
    profile_form.wait_for(state="visible", timeout=10_000)
    pace(page, 400)

    narrate(page, "give_party_name")
    _fill(page, profile_form.locator("input[name='name']"), PARTY_NAME)
    hover_and_click(page, profile_form.locator("input[name='is_default']"))
    pace(page, 400)

    hover_and_click(page, profile_form.get_by_role("button", name="Add entity").first)
    entity_card = page.locator(".entity-card").first
    editor = entity_card.locator(".entity-editor-content")
    editor.wait_for(state="visible", timeout=5_000)
    pace(page, 400)

    narrate(page, "entity_organization_pied")
    # A cloned entity does not always keep the template's ticked roles, so
    # click only the boxes that are not already in the wanted state.
    for role, wanted in (("is_manufacturer", True), ("is_supplier", True), ("is_author", False)):
        box = entity_card.locator(f"input[name$='-{role}']").first
        if box.is_checked() != wanted:
            hover_and_click(page, box, pause_ms=150)
            pace(page, 250)
    pace(page, 300)

    _fill(page, editor.locator("input[placeholder='e.g. Acme Corporation']"), "Pied Piper Inc")
    _fill(page, editor.locator("input[placeholder='contact@example.com']"), "compliance@example.com")
    _fill(page, editor.locator("input[placeholder='+1 555 123 4567']"), "+1 650 555 0142")
    narrate(page, "address_website_fill")
    _fill(page, editor.locator("textarea[name$='-address']"), "5230 Newell Road, Palo Alto, CA 94303", delay=40)
    _fill(page, editor.locator("textarea[name$='-website_urls_text']"), "https://piedpiper.example.com", delay=40)

    add_contact = entity_card.get_by_role("button", name="Add contact")
    smooth_scroll(page, add_contact, 400)
    narrate(page, "every_entity_needs")
    hover_and_click(page, add_contact)
    contact1 = entity_card.locator(".contact-card").first
    contact1.wait_for(state="visible", timeout=5_000)
    pace(page, 300)
    _fill(page, contact1.locator("input[aria-label='Contact Name']"), "Bertram Gilfoyle")
    _fill(page, contact1.locator("input[aria-label='Contact Email']"), "gilfoyle@example.com")
    narrate(page, "gilfoyle_security_contact")
    for role in ("is_security_contact", "is_technical_contact"):
        hover_and_click(page, contact1.locator(f"input[name$='-{role}']"), pause_ms=150)
        pace(page, 250)

    hover_and_click(page, add_contact)
    contact2 = entity_card.locator(".contact-card").nth(1)
    contact2.wait_for(state="visible", timeout=5_000)
    pace(page, 300)
    _fill(page, contact2.locator("input[aria-label='Contact Name']"), "Dinesh Chugtai")
    _fill(page, contact2.locator("input[aria-label='Contact Email']"), "dinesh@example.com")
    hover_and_click(page, contact2.locator("input[name$='-is_technical_contact']"), pause_ms=150)
    pace(page, 400)

    done_btn = entity_card.get_by_role("button", name="Done")
    smooth_scroll(page, done_btn, 400)
    narrate(page, "click_done_close")
    hover_and_click(page, done_btn)
    pace(page, 1200)

    create_btn = profile_form.get_by_role("button", name="Create party")
    narrate(page, "create_party")
    hover_and_click(page, create_btn)

    content.get_by_role("table", name="Parties").wait_for(state="visible", timeout=15_000)
    page.wait_for_load_state("networkidle")
    pace(page, 600)
    narrate(page, "party_saved_marked")
    settle(page)
    pace(page, 500)
