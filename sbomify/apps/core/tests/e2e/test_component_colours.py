"""Rendered component ink must match the live palette in each theme.

Status ink is its own token: a status reads as a fill in one place and as text
on a tint of itself in another, and on a white surface those cannot be the same
value. test_component_contrast.py is what checks the ink is readable; this file
checks the component reached for the right one.
"""

import pytest
from playwright.sync_api import Locator, Page, expect

from sbomify.apps.core.tests.test_design_system_view import _debug_urlconf_fixture

debug_gallery = _debug_urlconf_fixture(True)


def token_colour(page: Page, token: str) -> str:
    return page.locator(f'[style="background-color: var(--color-{token})"]').evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )


def assert_ink(elements: Locator, colour: str) -> None:
    assert elements.count(), "The colour check must exercise a rendered component"
    for element in elements.all():
        expect(element).to_have_css("color", colour)


@pytest.mark.django_db
@pytest.mark.usefixtures("debug_gallery")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_component_foregrounds_match_the_palette(authenticated_page: Page, theme: str) -> None:
    page = authenticated_page
    page.add_init_script(f"localStorage.setItem('sbomify-theme', '{theme}');")
    page.goto("/design-system/")
    expect(page.get_by_role("heading", name="Colour tokens", exact=True)).to_be_attached()

    # The value is read, so it takes the ink. The icon is decorative and
    # aria-hidden, a soft mark on a tint of the same accent, so it keeps the
    # accent itself: the two are deliberately not the same colour.
    for label, ink_token, accent_token in [
        ("Components with stale SBOMs", "warning-ink", "warning"),
        ("Past your patch SLA", "danger-ink", "danger"),
        ("NTIA compliant", "success-ink", "success"),
    ]:
        card = page.locator("dl").filter(has_text=label)
        assert_ink(card.locator("dd"), token_colour(page, ink_token))
        if card.locator("dt i").count():
            assert_ink(card.locator("dt i"), token_colour(page, accent_token))
    zero = page.locator("#app-overview dl").filter(has_text="Known exploited occurrences")
    assert_ink(zero.locator("dd"), token_colour(page, "text"))
    assert_ink(zero.locator("dt i"), token_colour(page, "text-muted"))

    for level in ("critical", "high", "medium", "low", "unknown"):
        token = "text-secondary" if level == "unknown" else f"severity-{level}"
        assert_ink(page.locator(f'[data-level="{level}"]'), token_colour(page, token))
    for status, token in [
        ("pass", "success-ink"),
        ("fail", "warning-ink"),
        ("pending", "info-ink"),
        ("error", "danger-ink"),
        ("summary-fail", "danger-ink"),
    ]:
        assert_ink(page.locator(f'[data-status="{status}"]'), token_colour(page, token))
    for format_name, token in [("cyclonedx", "success-ink"), ("spdx", "accent-ink")]:
        assert_ink(page.locator(f'[data-format="{format_name}"]'), token_colour(page, token))
    assert_ink(page.get_by_text("Passed", exact=True).locator("..").locator("i"), token_colour(page, "success"))
    assert_ink(page.locator("code").filter(has_text="CRA-13-4"), token_colour(page, "primary"))
    assert_ink(page.get_by_role("button", name="Warning", exact=True), token_colour(page, "navy"))

    # The same colour contract applies when Alpine updates a zero stat in place.
    pending = page.locator("dl").filter(has_text="Pending assessments")
    assert_ink(pending.locator("dd"), token_colour(page, "text"))
    page.get_by_role("button", name="Toggle example count", exact=True).click()
    assert_ink(pending.locator("dd"), token_colour(page, "warning-ink"))
    assert_ink(pending.locator("dt i"), token_colour(page, "warning"))
