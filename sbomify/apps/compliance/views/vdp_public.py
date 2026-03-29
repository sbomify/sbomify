"""Public VDP and security.txt views for the trust center."""

from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import urlparse

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.utils.safestring import mark_safe
from django.views import View

from sbomify.apps.compliance.models import CRAAssessment, CRAGeneratedDocument

logger = logging.getLogger(__name__)

_SAFE_URL_SCHEMES = frozenset(("http", "https", "mailto"))


def _sanitize_url(url: str) -> str:
    """Only allow safe URL schemes to prevent javascript:/data: XSS."""
    parsed = urlparse(url)
    if parsed.scheme not in _SAFE_URL_SCHEMES:
        return "#"
    return url


def _markdown_to_html(text: str) -> str:
    """Convert simple Markdown to HTML. Handles headings, bold, italic, links, lists, hr, paragraphs."""
    escaped = html.escape(text)
    lines = escaped.split("\n")
    result: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Horizontal rule
        if re.fullmatch(r"-{3,}", stripped):
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
            result.append(f"<h{level}>{_inline_markup(m.group(2))}</h{level}>")
            continue

        # List items
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                result.append("<ul>")
                in_list = True
            result.append(f"<li>{_inline_markup(stripped[2:])}</li>")
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
        result.append(f"<p>{_inline_markup(stripped)}</p>")

    if in_list:
        result.append("</ul>")

    return "\n".join(result)


def _inline_markup(text: str) -> str:
    """Convert inline Markdown: bold, italic, links.

    URLs are sanitized to only allow http, https, and mailto schemes.
    """

    def _safe_link(m: re.Match[str]) -> str:
        link_text = m.group(1)
        url = _sanitize_url(m.group(2))
        return f'<a href="{url}" class="text-primary hover:underline">{link_text}</a>'

    # Links: [text](url) — sanitize URL scheme
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _safe_link, text)
    # Bold: **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic: *text*
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    # Inline code: `text`
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


class ProductVDPPublicView(View):
    """Render the VDP document as a public trust center page."""

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        from sbomify.apps.core.models import Product

        try:
            product = Product.objects.select_related("team").get(pk=product_id)
        except Product.DoesNotExist:
            return HttpResponseNotFound("Product not found")

        # Check product is publicly visible
        if not product.is_public:
            return HttpResponseNotFound("Product not found")

        # Get the VDP document
        vdp_content = _get_document_content(product, CRAGeneratedDocument.DocumentKind.VDP)
        if not vdp_content:
            return HttpResponseNotFound("No VDP available for this product")

        # Safe: _markdown_to_html escapes all input via html.escape() before adding markup
        vdp_html = mark_safe(_markdown_to_html(vdp_content))  # nosec B703 B308  # noqa: S308

        return render(
            request,
            "compliance/vdp_public.html.j2",
            {
                "product": product,
                "vdp_html": vdp_html,
                "is_custom_domain": getattr(request, "is_custom_domain", False),
            },
        )


class SecurityTxtView(View):
    """Serve CRA-generated security.txt at /.well-known/security.txt for custom domains."""

    def get(self, request: HttpRequest) -> HttpResponse:
        # Require custom domain context (consistent with TEAWellKnownView)
        if not getattr(request, "is_custom_domain", False):
            return HttpResponseNotFound("Not found")

        team = getattr(request, "custom_domain_team", None)
        if not team:
            return HttpResponseNotFound("Not found")

        # Workspace must be public
        if not team.is_public:
            return HttpResponseNotFound("Not found")

        # For BYOD custom domains, require validation
        if not getattr(request, "is_trust_center_subdomain", False) and not getattr(
            team, "custom_domain_validated", False
        ):
            return HttpResponseNotFound("Not found")

        # Find the most recently generated security.txt across all team assessments
        doc = (
            CRAGeneratedDocument.objects.filter(
                assessment__team=team,
                document_kind=CRAGeneratedDocument.DocumentKind.SECURITY_TXT,
            )
            .order_by("-generated_at")
            .first()
        )

        if not doc:
            return HttpResponseNotFound("Not found")

        content = _fetch_doc_from_s3(doc)
        if not content:
            return HttpResponseNotFound("Not found")

        return HttpResponse(content, content_type="text/plain; charset=utf-8")


def _get_document_content(product: Any, document_kind: str) -> str | None:
    """Get rendered document content for a product's CRA assessment."""
    try:
        assessment = CRAAssessment.objects.get(product=product)
    except CRAAssessment.DoesNotExist:
        return None

    doc = CRAGeneratedDocument.objects.filter(
        assessment=assessment,
        document_kind=document_kind,
    ).first()

    if not doc:
        return None

    return _fetch_doc_from_s3(doc)


def _fetch_doc_from_s3(doc: CRAGeneratedDocument) -> str | None:
    """Fetch document content from S3 and return as string."""
    try:
        from sbomify.apps.core.object_store import StorageClient

        s3 = StorageClient("DOCUMENTS")
        data = s3.get_document_data(doc.storage_key)
        return data.decode("utf-8") if data else None
    except Exception:
        logger.exception("Failed to fetch document %s from S3", doc.storage_key)
        return None
