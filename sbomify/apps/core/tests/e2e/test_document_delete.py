"""Deleting a document from the component page, through the confirmation dialog.

The dialog's form is wired by HTMX, and HTMX can only wire what it can reach
when it walks the swapped content. That wiring is what a Django-client test
cannot observe: the view underneath already had coverage and kept passing while
the Delete button in front of it submitted a GET of the current page, so the
page reloaded unchanged and the document stayed.
"""

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.documents.models import Document


@pytest.mark.django_db
class TestDocumentDeletion:
    def test_confirming_the_dialog_deletes_the_document(
        self,
        authenticated_page: Page,
        document_component_details,
    ) -> None:
        document = Document.objects.get(component=document_component_details)

        authenticated_page.goto(f"/component/{document_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        row_link = authenticated_page.get_by_role("link", name=document.name)
        expect(row_link).to_be_visible()

        # The menu closes on any scroll, because it is teleported and fixed and
        # cannot follow a scrolling ancestor. Playwright scrolls the trigger
        # into view as part of clicking it, and that scroll event can land
        # after the click, so settle the page first and the menu stays open.
        trigger = authenticated_page.get_by_role("button", name="Document actions").first
        trigger.scroll_into_view_if_needed()
        authenticated_page.wait_for_timeout(300)
        trigger.click()

        delete_item = authenticated_page.get_by_role("menuitem", name="Delete", exact=True)
        expect(delete_item).to_be_visible()
        delete_item.click()

        expect(authenticated_page.locator("#delete-document-modal-label")).to_be_visible()
        authenticated_page.get_by_role("button", name="Delete Document").click()

        # The table reloads on the view's HX-Trigger, so the row going is the
        # same signal the user gets. A page that navigated instead would still
        # be showing the row here.
        expect(row_link).to_have_count(0)
        expect(authenticated_page).to_have_url(f"/component/{document_component_details.id}/")
        assert not Document.objects.filter(id=document.id).exists()
