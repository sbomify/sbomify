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
    """Only allow safe URL schemes to prevent javascript:/data: XSS.

    A URL ``urlparse`` cannot read, such as an unbalanced IPv6 bracket,
    is unsafe too: raising here would fail the whole page.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "#"
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
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme in ("http", "https"):
        return url
    return None


_LIST_ITEM_RE = re.compile(r"^( *)([-*+]|\d{1,9}[.)])\s+(.*)$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LINK_REL = "nofollow ugc noopener noreferrer"


def markdown_to_html(text: str) -> str:
    """Convert Markdown to HTML.

    Handles headings, paragraphs, bold, italic, links, bare URLs, inline
    code, fenced code blocks, thematic breaks, and bulleted and numbered
    lists, nested by indentation. Intentionally a subset: the wizard
    preview uses ``marked.js`` for the full CommonMark surface, and the
    public pages only need what generated documents and advisory text
    actually use. Consecutive lines join into one paragraph, as in
    CommonMark, so hard-wrapped text reads as prose rather than a stack
    of one-line paragraphs.
    """
    escaped = html.escape(text)
    result: list[str] = []
    paragraph: list[str] = []
    # Whether the open paragraph is quoted (``> ...`` lines).
    quoted = False
    # Open lists, innermost last, as (indent, tag). An item's ``<li>`` stays
    # open until the next item at its level, so a nested list lands inside it.
    lists: list[tuple[int, str]] = []
    fence: str | None = None
    fence_lines: list[str] = []
    previous_blank = False

    def flush_paragraph() -> None:
        if paragraph:
            body = f"<p>{inline_markup(' '.join(paragraph))}</p>"
            result.append(f"<blockquote>{body}</blockquote>" if quoted else body)
            paragraph.clear()

    def close_list() -> None:
        _, tag = lists.pop()
        result[-1] += "</li>"
        result.append(f"</{tag}>")

    def close_lists() -> None:
        while lists:
            close_list()

    for raw_line in escaped.split("\n"):
        line = raw_line.replace("\t", "    ").rstrip()
        stripped = line.strip()

        if fence is not None:
            if stripped.startswith(fence):
                result.append(f"<pre><code>{chr(10).join(fence_lines)}</code></pre>")
                fence, fence_lines = None, []
                previous_blank = False
            else:
                fence_lines.append(line)
            continue

        if m := _FENCE_RE.match(line):
            flush_paragraph()
            close_lists()
            fence = m.group(1)
            continue

        if not stripped:
            flush_paragraph()
            previous_blank = True
            continue

        # Thematic break. CommonMark accepts ``---``, ``***`` and ``___``;
        # the DoC template uses ``***`` for the closing rule because
        # ``---`` would be ambiguous with a setext heading underline
        # when it follows a paragraph. Checked before list items, which
        # ``***`` would otherwise also match.
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            flush_paragraph()
            close_lists()
            result.append("<hr>")
            previous_blank = False
            continue

        if m := re.match(r"^(#{1,6})\s+(.+)$", stripped):
            flush_paragraph()
            close_lists()
            level = len(m.group(1))
            result.append(f"<h{level}>{inline_markup(m.group(2))}</h{level}>")
            previous_blank = False
            continue

        if m := _LIST_ITEM_RE.match(line):
            flush_paragraph()
            indent = len(m.group(1))
            marker = m.group(2)
            tag = "ul" if marker in "-*+" else "ol"
            while lists and lists[-1][0] > indent:
                close_list()
            if lists and lists[-1][0] == indent:
                if lists[-1][1] == tag:
                    result[-1] += "</li>"
                else:
                    close_list()
            if not lists or lists[-1][0] < indent:
                start = int(marker[:-1]) if tag == "ol" else 1
                result.append(f'<{tag} start="{start}">' if start != 1 else f"<{tag}>")
                lists.append((indent, tag))
            result.append(f"<li>{inline_markup(m.group(3))}")
            previous_blank = False
            continue

        # Text under an open list item continues it: straight after the item,
        # or after a blank line when indented under it. Anything else ends
        # the lists and starts a paragraph.
        if lists and (not previous_blank or len(line) - len(line.lstrip()) > lists[-1][0]):
            result[-1] += f" {inline_markup(stripped)}"
            previous_blank = False
            continue

        close_lists()
        # ``html.escape`` has already turned the quote marker into ``&gt;``.
        is_quote = stripped.startswith("&gt;")
        if is_quote != quoted:
            flush_paragraph()
            quoted = is_quote
        paragraph.append(stripped.removeprefix("&gt;").strip() if is_quote else stripped)
        previous_blank = False

    if fence is not None:
        result.append(f"<pre><code>{chr(10).join(fence_lines)}</code></pre>")
    flush_paragraph()
    close_lists()

    return "\n".join(result)


def _trim_autolink(url: str) -> str:
    """Drop trailing punctuation a sentence put after a bare URL.

    A closing parenthesis stays when the URL opened one itself, as
    Wikipedia-style links do.
    """
    while url:
        last = url[-1]
        if last in ".,;:!?'" or (last == ")" and url.count(")") > url.count("(")):
            url = url[:-1]
        elif url.endswith(("&quot;", "&#x27;")):
            url = url[: url.rindex("&")]
        else:
            break
    return url


def inline_markup(text: str) -> str:
    """Convert inline Markdown: bold, italic, links, bare URLs, code spans.

    URLs are sanitized to only allow http, https, and mailto schemes.
    Every link carries ``rel="nofollow ugc noopener noreferrer"``: the
    text is written by users and shown on public, indexed pages.

    Code spans and bare URLs are stashed with NUL-byte sentinels *before*
    the other inline passes run, so markdown metacharacters inside
    backticks or a URL — glob ``*``, link syntax, asterisks meant as
    literal text — survive the bold/italic/link regexes verbatim. This
    matches Markdown's "code spans win over other inline constructs"
    precedence.
    """
    stash: list[str] = []
    # Bare URLs by stash slot, so a link whose text holds one shows it as text
    # rather than nesting one anchor inside another.
    autolinks: dict[str, str] = {}

    def _put(value: str) -> str:
        stash.append(value)
        return f"\x00{len(stash) - 1}\x00"

    # Stash code spans first so their contents are not re-parsed.
    text = re.sub(r"`([^`]+)`", lambda m: _put(f"<code>{m.group(1)}</code>"), text)

    # Bare URLs. One that is a link or image target ``](url)``, opens link
    # text ``[url``, or sits inside a word or path is left for the passes
    # below.
    def _autolink(m: re.Match[str]) -> str:
        url = _trim_autolink(m.group(0))
        trailing = m.group(0)[len(url) :]
        href = html.escape(sanitize_url(html.unescape(url)), quote=True)
        slot = _put(f'<a href="{href}" rel="{_LINK_REL}" class="text-primary hover:underline">{url}</a>')
        autolinks[slot] = url
        return slot + trailing

    text = re.sub(r"(?<![\w/\[=\"])(?<!\]\()https?://[^\s<>\[\]\x00]+", _autolink, text)

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
    #
    # Link text and URL are unescaped before they are escaped, so text that
    # ``markdown_to_html`` already escaped is not escaped twice: a query
    # string's ``&`` would otherwise reach the ``href`` as ``&amp;amp;`` and
    # the link would point somewhere else.
    def _safe_link(m: re.Match[str]) -> str:
        label = m.group(1)
        for slot, url in autolinks.items():
            label = label.replace(slot, url)
        link_text = html.escape(html.unescape(label), quote=True)
        url = html.escape(sanitize_url(html.unescape(m.group(2))), quote=True)
        return f'<a href="{url}" rel="{_LINK_REL}" class="text-primary hover:underline">{link_text}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _safe_link, text)
    # Bold: **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic: *text*
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)

    # Restore the stash now that the other inline passes have run. Newest
    # first, so a code span inside link text is restored after its link.
    for i in reversed(range(len(stash))):
        text = text.replace(f"\x00{i}\x00", stash[i])
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


# Matches the entire ``- **Place:** …`` bullet so we can drop it from
# the public render. The trailing newline is optional so a Place bullet
# at end-of-file (e.g. an S3 blob that was trimmed before storage) is
# still removed; otherwise the sensitive value would leak whenever it
# happens to be the final line. The PDF and bundle export hold the
# original markdown — only the public trust-center view fetches it
# through this helper. CRA Annex V Section 8 still requires Place to be
# present in the authoritative DoC; the auditor / notified body sees
# the unredacted value via the export ZIP.
_DOC_PLACE_LINE_RE = re.compile(r"^- \*\*Place:\*\* .+(?:\n|$)", re.MULTILINE)


def remove_signature_place_for_public(markdown: str) -> str:
    """Strip the Place bullet entirely from the DoC markdown for public display.

    Earlier iterations rendered ``Place: _Redacted_`` but that's noise
    — readers learn nothing useful from a placeholder. Dropping the
    bullet outright keeps the public DoC focused on the data we DO
    want to surface (Date, Name, Function, Signature). The stored
    markdown is the regulator-facing source of truth and is not
    modified.
    """
    return _DOC_PLACE_LINE_RE.sub("", markdown)


def fetch_doc_from_s3(doc: CRAGeneratedDocument) -> str | None:
    """Fetch document content from S3 and return as string."""
    try:
        from sbomify.apps.core.object_store import StorageClient

        s3 = StorageClient("DOCUMENTS")
        data = s3.get_document_data(doc.storage_key)
        return data.decode("utf-8") if data else None
    except Exception:
        logger.exception("Failed to fetch document %s from S3", doc.storage_key)
        return None
