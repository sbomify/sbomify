"""Public VDP and security.txt views for the trust center.

The shared markdown / S3 helpers used to live here as underscore-
prefixed module locals; they have been moved to
``views/_public_helpers.py`` so the DoC public view (and any future
trust-center reader) can import them without reaching into another
view module's private API.
"""

from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.utils.safestring import mark_safe
from django.views import View

from sbomify.apps.compliance.models import CRAGeneratedDocument
from sbomify.apps.compliance.views._public_helpers import (
    fetch_doc_from_s3,
    get_document_content,
    markdown_to_html,
)

logger = logging.getLogger(__name__)


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
        vdp_content = get_document_content(product, CRAGeneratedDocument.DocumentKind.VDP)
        if not vdp_content:
            return HttpResponseNotFound("No VDP available for this product")

        # Safe: markdown_to_html escapes all input via html.escape() before adding markup
        vdp_html = mark_safe(markdown_to_html(vdp_content))  # nosec B703 B308  # noqa: S308

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

        content = fetch_doc_from_s3(doc)
        if not content:
            return HttpResponseNotFound("Not found")

        return HttpResponse(content, content_type="text/plain; charset=utf-8")
