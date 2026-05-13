"""Public Declaration of Conformity view for the trust center.

The DoC is the only Annex V document a third party (auditor, customer,
notified body) needs to read directly. Section 5 of the public product
page exposes a "View Declaration" link that resolves here. The card is
only rendered, and the route only succeeds, when:

1. The product is publicly visible.
2. A CRA assessment exists for the product and is in ``complete``
   status — partial / draft assessments are not authoritative and must
   not be exposed.
3. A ``CRAGeneratedDocument`` of kind ``DECLARATION_OF_CONFORMITY``
   has been rendered to S3 **and** is not flagged ``is_stale=True``.
   Staleness fires when the underlying inputs (product details,
   manufacturer entity, controls) change after generation; surfacing
   a stale DoC on the public trust center would mislead consumers.

Other Annex VII artefacts (risk assessment, decommissioning guide,
Article 14 templates) are intentionally NOT exposed publicly: they
ship inside the export ZIP for review by an auditor or notified body,
not via the trust center.
"""

from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.utils.safestring import mark_safe
from django.views import View

from sbomify.apps.compliance.models import CRAAssessment, CRAGeneratedDocument
from sbomify.apps.compliance.views._public_helpers import fetch_doc_from_s3, markdown_to_html

logger = logging.getLogger(__name__)


class ProductDoCPublicView(View):
    """Render the Declaration of Conformity as a public trust-center page."""

    def get(self, request: HttpRequest, product_id: str) -> HttpResponse:
        from sbomify.apps.core.models import Product

        try:
            product = Product.objects.select_related("team").get(pk=product_id)
        except Product.DoesNotExist:
            return HttpResponseNotFound("Product not found")

        if not product.is_public:
            return HttpResponseNotFound("Product not found")

        # CRA gating: only a *complete* assessment with a *fresh* DoC
        # is authoritative enough to expose. A draft / in-progress
        # assessment, OR a complete assessment whose DoC has been
        # marked stale by a downstream change (product rename,
        # manufacturer update, control flip) must 404 here so
        # customers never see a half-finished or out-of-date
        # declaration.
        try:
            assessment = CRAAssessment.objects.get(product=product)
        except CRAAssessment.DoesNotExist:
            return HttpResponseNotFound("No Declaration of Conformity for this product")

        if assessment.status != CRAAssessment.WizardStatus.COMPLETE:
            return HttpResponseNotFound("No Declaration of Conformity for this product")

        doc = CRAGeneratedDocument.objects.filter(
            assessment=assessment,
            document_kind=CRAGeneratedDocument.DocumentKind.DECLARATION_OF_CONFORMITY,
            is_stale=False,
        ).first()
        if doc is None:
            return HttpResponseNotFound("No Declaration of Conformity for this product")

        content = fetch_doc_from_s3(doc)
        if not content:
            return HttpResponseNotFound("No Declaration of Conformity for this product")

        # Safe: markdown_to_html escapes all input via html.escape() before adding markup.
        doc_html = mark_safe(markdown_to_html(content))  # nosec B703 B308  # noqa: S308

        return render(
            request,
            "compliance/doc_public.html.j2",
            {
                "product": product,
                "doc_html": doc_html,
                "is_custom_domain": getattr(request, "is_custom_domain", False),
            },
        )
