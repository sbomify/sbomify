"""Markdown for the notes people write in the app: advisory updates and VEX comments."""

from __future__ import annotations

import html
import re

from django import template
from django.utils.safestring import SafeString, mark_safe

from sbomify.apps.compliance.views._public_helpers import markdown_to_html

register = template.Library()

_HEADING_RE = re.compile(r"<h([1-6])>(.*?)</h\1>")


@register.filter
def strict_markdown(text: object) -> SafeString:
    """A note rendered from Markdown to HTML.

    Uses the trust center's strict renderer: the note is HTML-escaped first, so
    only the markup that renderer adds (headings, lists, bold, italic, code and
    links with safe schemes) ever reaches the page.

    Text that is already a SafeString was escaped by the template that built
    it, a quoted cotton attribute such as description="{{ advisory.description }}".
    It is unescaped before rendering, so it is escaped exactly once whichever
    way the caller passed it, rather than showing & as &amp;.
    """
    if not isinstance(text, str):
        return SafeString("")
    if isinstance(text, SafeString):
        text = html.unescape(text)
    # Safe: markdown_to_html escapes all input via html.escape() before adding markup.
    return mark_safe(markdown_to_html(text))  # nosec B703 B308  # noqa: S308


@register.filter
def strict_markdown_flat(text: object) -> SafeString:
    """strict_markdown with each heading rendered as a bold paragraph.

    For a note shown inside a page that owns its own outline: a "## Summary" in
    an advisory description is not a section of the advisory page, and as a
    real <h2> it would be listed among the page's sections by a screen reader.
    """
    # Safe: the input is strict_markdown's escaped output; only its own tags are rewritten.
    return mark_safe(_HEADING_RE.sub(r"<p><strong>\2</strong></p>", strict_markdown(text)))  # nosec B703 B308  # noqa: S308
