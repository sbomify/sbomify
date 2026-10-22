"""Markdown for the notes people write in the app: advisory updates and VEX comments."""

from __future__ import annotations

from django import template
from django.utils.safestring import SafeString, mark_safe

from sbomify.apps.compliance.views._public_helpers import markdown_to_html

register = template.Library()


@register.filter
def strict_markdown(text: object) -> SafeString:
    """A note rendered from Markdown to HTML.

    Uses the trust center's strict renderer: the note is HTML-escaped first, so
    only the markup that renderer adds (headings, lists, bold, italic, code and
    links with safe schemes) ever reaches the page.
    """
    if not isinstance(text, str):
        return SafeString("")
    # Safe: markdown_to_html escapes all input via html.escape() before adding markup.
    return mark_safe(markdown_to_html(text))  # nosec B703 B308  # noqa: S308
