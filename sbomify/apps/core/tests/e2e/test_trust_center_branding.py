"""What the workspace accent may and may not repaint on a public page.

`public_base.htmx.j2` carries a legacy rule that colours every anchor it does
not recognise with the workspace accent. It is deliberately broad, and it is
what makes a plain link on a trust center pick up the brand. The cost is that a
component whose anchor is meant to stay neutral is one stylesheet away from
being repainted, and nothing in a template test can see it: the cascade only
resolves in a browser.

So this measures it in one. The control case proves the rule is live, which is
what stops the other assertions passing for the wrong reason if the rule is ever
dropped.
"""

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403

# A workspace accent no platform token uses, so a repaint is unambiguous.
ACCENT = "#C2410C"
ACCENT_RGB = "rgb(194, 65, 12)"
PLATFORM_TEXT_RGB = "rgb(37, 41, 63)"


@pytest.mark.django_db
def test_the_accent_repaints_a_plain_link_but_not_a_record_heading(
    authenticated_page: Page,
    trust_center_product,  # noqa: F811
) -> None:
    team = trust_center_product.team
    team.branding_info = {**(team.branding_info or {}), "accent_color": ACCENT}
    team.save()

    authenticated_page.goto(f"/public/workspace/{team.key}/")
    authenticated_page.wait_for_load_state("networkidle")

    colours = authenticated_page.evaluate(
        """() => {
            const colour = (selector) => {
                const element = document.querySelector(selector);
                return element ? getComputedStyle(element).color : 'MISSING';
            };
            return {
                plainLink: colour('#products a:not([data-button])'),
                credential: colour('#certifications a'),
                record: colour('#compliance a'),
            };
        }"""
    )

    # The control: the rule is live, so the two below mean something.
    assert colours["plainLink"] == ACCENT_RGB, colours

    # A certification label names the record, so it stays the platform's text
    # colour. A pale accent here would make the seal's own label unreadable.
    assert colours["credential"] == PLATFORM_TEXT_RGB, colours
    assert colours["record"] == PLATFORM_TEXT_RGB, colours
