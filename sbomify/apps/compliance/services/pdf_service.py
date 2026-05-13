"""Render CRA bundle markdown documents to PDF.

The CRA export bundle (``services/export_service.py``) ships every
generated document as ``.md`` so machine consumers can hash, diff, and
re-render the source. Auditors and notified bodies, on the other hand,
overwhelmingly want a PDF — the regulatory-filing chain still runs on
paper-shaped artefacts. This module bridges the two: it consumes the
same markdown the bundle already writes and produces a styled PDF
beside it, so the ZIP carries both copies.

Pipeline:

    markdown source
        → ``markdown_to_html`` (existing helper, already accepts the
          signature ``data:image/png;base64,`` URL safely)
        → wrapped in a styled HTML5 document with CSS ``@page`` rules
        → WeasyPrint
        → PDF bytes

WeasyPrint requires Pango ≥1.4.4 at runtime. The Dockerfile installs
the libs in the ``python-common-code`` stage so dev/test work. If the
import or render fails for any reason (missing libs in a stripped
runtime, font issues, malformed input) we log and return ``None`` —
the caller continues with the ``.md`` copy. PDF here is a convenience
rendering, not load-bearing for compliance: the ``.md`` is the source
of truth that auditors verify against the manifest hash.
"""

from __future__ import annotations

import html
import logging
from typing import cast

from sbomify.apps.compliance.views._public_helpers import markdown_to_html

logger = logging.getLogger(__name__)


# Embedded CSS for the rendered PDF. Kept in this module (not a static
# file) so the rendering pipeline has zero file-system dependency at
# runtime — important because the prod image is distroless and the
# CRA bundle build runs inside a Dramatiq worker that may not have
# the same working directory layout as the web frontend.
_PRINT_CSS = """
@page {
    size: A4;
    margin: 2cm 2cm 2.5cm 2cm;
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-family: "Helvetica", "Arial", sans-serif;
        font-size: 9pt;
        color: #666;
    }
}

body {
    font-family: "Helvetica", "Arial", sans-serif;
    font-size: 10.5pt;
    line-height: 1.5;
    color: #1a1a1a;
}

h1 {
    font-size: 20pt;
    color: #0f172a;
    border-bottom: 2px solid #0f172a;
    padding-bottom: 0.3em;
    margin-top: 0;
}

h2 {
    font-size: 14pt;
    color: #1e293b;
    margin-top: 1.5em;
    page-break-after: avoid;
}

h3 {
    font-size: 12pt;
    color: #334155;
    margin-top: 1.2em;
    page-break-after: avoid;
}

p, ul, ol {
    margin: 0.5em 0;
}

ul, ol {
    padding-left: 1.5em;
}

li {
    margin: 0.2em 0;
}

a {
    color: #1d4ed8;
    text-decoration: none;
}

code {
    font-family: "Menlo", "Consolas", monospace;
    font-size: 9.5pt;
    background-color: #f1f5f9;
    padding: 1px 4px;
    border-radius: 3px;
}

hr {
    border: none;
    border-top: 1px solid #cbd5e1;
    margin: 1.5em 0;
}

img {
    max-width: 100%;
    page-break-inside: avoid;
}

/* Inline signature image needs explicit height so it doesn't
   stretch to canvas resolution. The Markdown renderer adds the
   ``inline-block max-h-24`` Tailwind classes for the HTML view;
   WeasyPrint ignores Tailwind, so we cap height directly. */
img[alt="Signature"] {
    max-height: 80px;
    display: inline-block;
    vertical-align: middle;
}

strong {
    color: #0f172a;
}
"""


def _wrap_html(body_html: str, *, title: str) -> str:
    """Wrap rendered body HTML in a minimal HTML5 document.

    WeasyPrint expects a full document with ``<html>`` / ``<head>`` so
    its CSS resolution starts from a known root. The title goes into
    the document metadata (visible in PDF readers' tab/title bar) and
    is also a useful breadcrumb for the auditor opening dozens of
    bundles in sequence. We HTML-escape the title in full (not just
    ``</``) so a hostile or malformed value can't break out of the
    ``<title>`` element via ``<``, ``>`` or ``&``.
    """
    safe_title = html.escape(title or "Document", quote=False)
    return (
        "<!doctype html>"
        f'<html lang="en"><head><meta charset="utf-8"><title>{safe_title}</title>'
        f"<style>{_PRINT_CSS}</style></head><body>{body_html}</body></html>"
    )


def markdown_to_pdf(md_text: str, *, title: str = "") -> bytes | None:
    """Render markdown to PDF bytes; return ``None`` on failure.

    Returns ``None`` rather than raising so a missing system dep
    (Pango, fontconfig) at runtime degrades the bundle export to
    ``.md`` only instead of aborting the whole package build. The
    failure is logged with the document title so operators can find
    the cause in the worker logs without losing the bundle.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except Exception:
        logger.warning("WeasyPrint unavailable; skipping PDF rendering for %r", title)
        return None

    try:
        body_html = markdown_to_html(md_text)
        full_html = _wrap_html(body_html, title=title or "Document")
        return cast(bytes, HTML(string=full_html).write_pdf())
    except Exception:
        logger.exception("PDF rendering failed for %r", title)
        return None
