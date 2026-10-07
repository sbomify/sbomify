"""Badge labels stay whole while their parent layout keeps controls reachable."""

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.test_cra_compliance import cra_assessment  # noqa: F401

pytest_plugins = ["sbomify.apps.core.tests.e2e.fixtures"]


@pytest.mark.django_db
@pytest.mark.parametrize("width", [320, 375, 576])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_document_status_badges_keep_controls_inside_mobile_cards(
    authenticated_page: Page,
    cra_assessment,  # noqa: F811
    width: int,
    theme: str,
) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"/compliance/cra/{cra_assessment.id}/step/5/")
    page.wait_for_load_state("networkidle")
    badges = page.get_by_text("Not generated", exact=True)
    assert badges.count() > 0
    for badge in badges.all():
        assert badge.evaluate("""el => {
            const actions = el.parentElement.getBoundingClientRect();
            const card = el.parentElement.parentElement.getBoundingClientRect();
            return getComputedStyle(el).whiteSpace === 'nowrap'
                && el.scrollWidth <= el.clientWidth
                && actions.left >= card.left && actions.right <= card.right;
        }""")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
