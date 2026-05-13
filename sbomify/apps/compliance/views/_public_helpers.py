"""Shared helpers for the public trust-center views.

The VDP and DoC public views both need to (a) fetch a generated
document blob from S3 and (b) render its markdown body to safe HTML.
Keeping these helpers underscore-private inside ``vdp_public.py``
forced the DoC view to import private symbols from a sibling
view module — Copilot flagged this on PR #934. Centralise here so
the helpers have a single, intentional home and either view can
import them without reaching into the other.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import urlparse

from sbomify.apps.compliance.models import CRAAssessment, CRAGeneratedDocument

logger = logging.getLogger(__name__)


_SAFE_URL_SCHEMES = frozenset(("http", "https", "mailto"))

# Image data URLs from the signature pad are the only ``data:`` scheme
# we render. Any other ``data:`` (text/html, javascript:, …) would be
# an XSS vector if the markdown renderer accepted it, so we keep the
# image handler separate from the link handler and only accept this
# exact prefix.
_SAFE_IMAGE_DATA_URL_PREFIX = "data:image/png;base64,"


def sanitize_url(url: str) -> str:
    """Only allow safe URL schemes to prevent javascript:/data: XSS."""
    parsed = urlparse(url)
    if parsed.scheme not in _SAFE_URL_SCHEMES:
        return "#"
    return url


def _safe_image_url(url: str) -> str | None:
    """Allow http(s) or our scoped ``data:image/png;base64`` payload.

    Returns ``None`` if the URL is not allowable so the caller can drop
    the image rather than emitting a broken ``<img>`` with a sanitized
    placeholder.
    """
    if url.startswith(_SAFE_IMAGE_DATA_URL_PREFIX):
        return url
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        return url
    return None


def markdown_to_html(text: str) -> str:
    """Convert simple Markdown to HTML.

    Handles headings, bold, italic, links, lists, thematic breaks,
    paragraphs, and inline code spans. Intentionally minimal — the
    wizard preview uses ``marked.js`` for the full CommonMark surface;
    the public reader only needs the subset our generated documents
    actually emit.
    """
    escaped = html.escape(text)
    lines = escaped.split("\n")
    result: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Thematic break. CommonMark accepts ``---``, ``***`` and ``___``;
        # the DoC template uses ``***`` for the closing rule because
        # ``---`` would be ambiguous with a setext heading underline
        # when it follows a paragraph.
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            if in_list:
                result.append("</ul>")
                in_list = False
            result.append("<hr>")
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            if in_list:
                result.append("</ul>")
                in_list = False
            level = len(m.group(1))
            result.append(f"<h{level}>{inline_markup(m.group(2))}</h{level}>")
            continue

        # List items
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                result.append("<ul>")
                in_list = True
            result.append(f"<li>{inline_markup(stripped[2:])}</li>")
            continue

        # Empty line
        if not stripped:
            if in_list:
                result.append("</ul>")
                in_list = False
            continue

        # Paragraph
        if in_list:
            result.append("</ul>")
            in_list = False
        result.append(f"<p>{inline_markup(stripped)}</p>")

    if in_list:
        result.append("</ul>")

    return "\n".join(result)


def inline_markup(text: str) -> str:
    """Convert inline Markdown: bold, italic, links, code spans.

    URLs are sanitized to only allow http, https, and mailto schemes.

    Code spans are stashed with NUL-byte sentinels *before* any other
    inline pass runs, so markdown metacharacters inside backticks —
    glob ``*``, link syntax, asterisks meant as literal text — survive
    the bold/italic/link regexes and end up inside the ``<code>``
    block verbatim. This matches Markdown's "code spans win over
    other inline constructs" precedence.
    """
    code_spans: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        code_spans.append(m.group(1))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    # Stash code spans first so their contents are not re-parsed.
    text = re.sub(r"`([^`]+)`", _stash, text)

    # Images: ![alt](url) — must run BEFORE links because both share
    # the ``[...](...)`` shape. The DoC uses this to embed the
    # signature PNG as a ``data:image/png;base64`` URL.
    #
    # Both ``_safe_image`` and ``_safe_link`` defensively HTML-escape
    # the alt / link text and the URL before emitting an ``<img>`` /
    # ``<a>`` tag. ``markdown_to_html`` already runs ``html.escape``
    # on the input, so for that callsite this is idempotent — but
    # ``inline_markup`` is exported (test suite + future callers
    # could pass raw markdown), and an attribute-context attacker
    # could otherwise break out via a literal ``"`` or ``>``.
    def _safe_image(m: re.Match[str]) -> str:
        alt = html.escape(m.group(1), quote=True)
        url = _safe_image_url(m.group(2))
        if url is None:
            # Drop the image entirely rather than emitting a broken
            # ``<img>``; the alt text becomes ordinary inline copy.
            return alt
        return f'<img src="{html.escape(url, quote=True)}" alt="{alt}" class="inline-block max-h-24">'

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _safe_image, text)

    # Links: [text](url) — sanitize URL scheme + escape attributes.
    def _safe_link(m: re.Match[str]) -> str:
        link_text = html.escape(m.group(1), quote=True)
        url = html.escape(sanitize_url(m.group(2)), quote=True)
        return f'<a href="{url}" class="text-primary hover:underline">{link_text}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _safe_link, text)
    # Bold: **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic: *text*
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)

    # Restore code spans now that the other inline passes have run.
    for i, span in enumerate(code_spans):
        text = text.replace(f"\x00CODE{i}\x00", f"<code>{span}</code>")
    return text


def get_document_content(product: Any, document_kind: str, *, fresh_only: bool = False) -> str | None:
    """Get rendered document content for a product's CRA assessment.

    When ``fresh_only=True`` the lookup also requires
    ``is_stale=False`` — set this for documents whose authoritative
    status matters publicly (DoC, etc.). The default keeps existing
    callers (VDP) on the original behaviour.
    """
    try:
        assessment = CRAAssessment.objects.get(product=product)
    except CRAAssessment.DoesNotExist:
        return None

    docs = CRAGeneratedDocument.objects.filter(
        assessment=assessment,
        document_kind=document_kind,
    )
    if fresh_only:
        docs = docs.filter(is_stale=False)
    doc = docs.first()

    if not doc:
        return None

    return fetch_doc_from_s3(doc)


def fetch_doc_from_s3(doc: CRAGeneratedDocument) -> str | None:
    """Fetch document content from S3 and return as string."""
    try:
        from sbomify.apps.core.object_store import S3Client

        s3 = S3Client("DOCUMENTS")
        data = s3.get_document_data(doc.storage_key)
        return data.decode("utf-8") if data else None
    except Exception:
        logger.exception("Failed to fetch document %s from S3", doc.storage_key)
        return None
