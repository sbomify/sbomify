"""The enterprise contact form shows each message in the colour of its level."""

import pytest
from django.contrib.messages import constants
from django.contrib.messages.storage.cookie import CookieStorage
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

TEXT = "Enterprise contact test message"


def _alert_holding(html: str, text: str) -> str:
    """The opening tag of the alert whose message is `text`."""
    start = html.rindex('<div class="@container/alert', 0, html.index(f">{text}</p>"))
    return html[start : html.index(">", start)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("level", "tag", "accent"),
    [
        (constants.SUCCESS, "success", "var(--color-success)"),
        (constants.ERROR, "error", "var(--color-danger)"),
        (constants.INFO, "info", "var(--color-primary)"),
    ],
)
def test_message_renders_in_its_level_colour(client, sample_user, level, tag, accent):
    storage = CookieStorage(RequestFactory().get("/"))
    storage.add(level, TEXT)
    response = HttpResponse()
    storage.update(response)
    client.cookies["messages"] = response.cookies["messages"].value
    client.force_login(sample_user)

    html = client.get(reverse("billing:enterprise_contact")).content.decode()

    assert f"[--alert-accent:{accent}]" in _alert_holding(html, TEXT)
    # The toast reads the same tag from the hidden list messages.html.j2 renders.
    assert f'<span data-level="{tag}">{TEXT}</span>' in html
